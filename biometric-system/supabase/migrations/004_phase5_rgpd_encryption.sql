-- ============================================================
-- BIOMETRIC SYSTEM — Phase 5: Chiffrement + RGPD + Rétention
-- À exécuter dans le SQL Editor Supabase APRÈS 003_phase3_kyc_access.sql
-- ============================================================

-- ============================================================
-- COLONNE: embedding_encrypted (chiffrement applicatif AES-GCM)
-- ============================================================
ALTER TABLE face_embeddings
    ADD COLUMN IF NOT EXISTS embedding_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS encryption_version  SMALLINT DEFAULT 1;

ALTER TABLE unknown_faces
    ADD COLUMN IF NOT EXISTS embedding_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS encryption_version  SMALLINT DEFAULT 1;


-- ============================================================
-- TABLE: consents (RGPD Art. 7)
-- ============================================================
CREATE TABLE IF NOT EXISTS consents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    identity_id     UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    purpose         TEXT NOT NULL,             -- biometric_recognition | kyc | analytics | access_control
    granted         BOOLEAN NOT NULL,
    document_url    TEXT,
    metadata        JSONB DEFAULT '{}',
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consents_identity ON consents(identity_id);
CREATE INDEX IF NOT EXISTS idx_consents_purpose  ON consents(purpose);
CREATE INDEX IF NOT EXISTS idx_consents_recent
    ON consents(identity_id, purpose, created_at DESC);

ALTER TABLE consents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_consents" ON consents
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: erasure_requests (Art. 17 — Right to be Forgotten)
-- Journal des effacements RGPD
-- ============================================================
CREATE TABLE IF NOT EXISTS erasure_requests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_id       UUID NOT NULL,             -- identity_id (référence morte: l'identité est supprimée)
    target_email    TEXT,
    requested_by    UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | completed | rejected
    embeddings_deleted  INT,
    events_anonymized   INT,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_erasure_status ON erasure_requests(status);
CREATE INDEX IF NOT EXISTS idx_erasure_target ON erasure_requests(target_id);

ALTER TABLE erasure_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_erasure" ON erasure_requests
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: retention_runs (historique des purges automatiques)
-- ============================================================
CREATE TABLE IF NOT EXISTS retention_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name      TEXT NOT NULL,
    cutoff          TIMESTAMPTZ NOT NULL,
    deleted_count   INT NOT NULL,
    duration_ms     INT,
    triggered_by    TEXT DEFAULT 'celery_beat',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retention_created ON retention_runs(created_at DESC);

ALTER TABLE retention_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_retention" ON retention_runs
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- RPC: anonymize_old_logs (utilisé par compliance/rgpd.py)
-- ============================================================
CREATE OR REPLACE FUNCTION anonymize_old_logs(days_threshold INT)
RETURNS JSONB
LANGUAGE plpgsql AS $$
DECLARE
    n_events INT;
    n_access INT;
    cutoff   TIMESTAMPTZ;
BEGIN
    cutoff := NOW() - (days_threshold || ' days')::INTERVAL;

    WITH updated AS (
        UPDATE recognition_events
           SET identity_id = NULL,
               metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                    '{anonymized_at}', to_jsonb(NOW()))
         WHERE created_at < cutoff AND identity_id IS NOT NULL
        RETURNING 1
    ) SELECT COUNT(*) INTO n_events FROM updated;

    WITH updated AS (
        UPDATE access_logs
           SET identity_id = NULL, reason = 'anonymized_retention'
         WHERE created_at < cutoff AND identity_id IS NOT NULL
        RETURNING 1
    ) SELECT COUNT(*) INTO n_access FROM updated;

    RETURN jsonb_build_object(
        'events_anonymized', COALESCE(n_events, 0),
        'access_logs_anonymized', COALESCE(n_access, 0),
        'cutoff', cutoff
    );
END;
$$;


-- ============================================================
-- VIEW: identity_compliance_view (statut RGPD par identité)
-- ============================================================
CREATE OR REPLACE VIEW identity_compliance_view AS
SELECT
    i.id              AS identity_id,
    i.full_name,
    i.email,
    i.status,
    COUNT(DISTINCT fe.id) AS embeddings_count,
    BOOL_OR(fe.embedding_encrypted IS NOT NULL) AS has_encrypted_embeddings,
    MAX(c.created_at) FILTER (WHERE c.granted) AS last_consent_grant,
    MAX(c.created_at) FILTER (WHERE NOT c.granted) AS last_consent_withdrawal,
    BOOL_OR(c.granted) AS has_active_consent
FROM identities i
LEFT JOIN face_embeddings fe ON fe.identity_id = i.id
LEFT JOIN consents c        ON c.identity_id = i.id
GROUP BY i.id;


-- ============================================================
-- Vue analytics (séries temporelles)
-- ============================================================
CREATE OR REPLACE VIEW recognition_events_hourly AS
SELECT
    date_trunc('hour', created_at) AS hour,
    event_type,
    COUNT(*) AS total
FROM recognition_events
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 1 DESC;
