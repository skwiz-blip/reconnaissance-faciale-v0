-- ============================================================
-- BIOMETRIC SYSTEM — Phase 6: Multi-tenant + Voice + Affect
--                              + Webhooks + Active learning + Drift
-- À exécuter dans le SQL Editor Supabase APRÈS 004_phase5_rgpd_encryption.sql
-- ============================================================

-- ============================================================
-- TABLE: tenants (SaaS multi-tenant)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code            TEXT UNIQUE NOT NULL,            -- slug: 'acme-corp'
    name            TEXT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'free',    -- free | pro | enterprise
    quotas          JSONB NOT NULL DEFAULT '{
        "recognitions_per_day": 1000,
        "identities_max":       100,
        "kyc_per_day":          50,
        "webhooks_max":         3
    }'::jsonb,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    contact_email   TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_code ON tenants(code);

DROP TRIGGER IF EXISTS trg_tenants_updated ON tenants;
CREATE TRIGGER trg_tenants_updated
    BEFORE UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_tenants" ON tenants
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: tenant_api_keys
-- (la clé en clair n'est jamais stockée, seulement son hash SHA-256)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,              -- "prod-key-1"
    key_hash        TEXT UNIQUE NOT NULL,       -- SHA-256 hex
    key_prefix      TEXT NOT NULL,              -- 8 premiers chars pour identification UI
    scopes          TEXT[] NOT NULL DEFAULT '{recognize,access}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash   ON tenant_api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON tenant_api_keys(tenant_id);

ALTER TABLE tenant_api_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_api_keys" ON tenant_api_keys
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- Ajout tenant_id sur les tables sensibles (idempotent)
-- ============================================================
ALTER TABLE identities          ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE face_embeddings     ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE recognition_events  ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE access_logs         ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE kyc_sessions        ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE unknown_faces       ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE zones               ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE access_policies     ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_identities_tenant         ON identities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_tenant    ON face_embeddings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_recognition_events_tenant ON recognition_events(tenant_id);


-- ============================================================
-- TABLE: voice_embeddings (256-D Resemblyzer)
-- ============================================================
CREATE TABLE IF NOT EXISTS voice_embeddings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    identity_id     UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    embedding       VECTOR(256),                -- en clair
    embedding_encrypted TEXT,                   -- chiffré AES-GCM (optionnel)
    quality_score   FLOAT DEFAULT 0.0,
    duration_seconds FLOAT,
    sample_rate     INT,
    source          TEXT DEFAULT 'enrollment',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_embeddings_identity ON voice_embeddings(identity_id);
CREATE INDEX IF NOT EXISTS idx_voice_embeddings_hnsw
    ON voice_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE voice_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_voice" ON voice_embeddings
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: affect_signals (emotions + stress sur events)
-- ============================================================
CREATE TABLE IF NOT EXISTS affect_signals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID REFERENCES recognition_events(id) ON DELETE CASCADE,
    identity_id     UUID REFERENCES identities(id),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    top_emotion     TEXT,
    emotion_confidence FLOAT,
    emotion_distribution JSONB,
    stress_level    TEXT,                       -- low | moderate | high
    stress_score    FLOAT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_affect_event    ON affect_signals(event_id);
CREATE INDEX IF NOT EXISTS idx_affect_identity ON affect_signals(identity_id);
CREATE INDEX IF NOT EXISTS idx_affect_created  ON affect_signals(created_at DESC);

ALTER TABLE affect_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_affect" ON affect_signals
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: webhooks
-- ============================================================
CREATE TABLE IF NOT EXISTS webhooks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    secret          TEXT NOT NULL,             -- partagé avec le partenaire
    events          TEXT[] NOT NULL,           -- ex: {'recognition.matched','access.denied'}
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON webhooks(tenant_id);

DROP TRIGGER IF EXISTS trg_webhooks_updated ON webhooks;
CREATE TRIGGER trg_webhooks_updated
    BEFORE UPDATE ON webhooks FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_webhooks" ON webhooks
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: webhook_deliveries (journal)
-- ============================================================
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    webhook_id      UUID NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | failed
    attempts        INT NOT NULL DEFAULT 0,
    http_status     INT,
    error           TEXT,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status  ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at DESC);

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_webhook_deliveries" ON webhook_deliveries
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: correction_candidates (active learning)
-- ============================================================
CREATE TABLE IF NOT EXISTS correction_candidates (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID REFERENCES tenants(id) ON DELETE CASCADE,
    event_id                UUID REFERENCES recognition_events(id) ON DELETE SET NULL,
    predicted_identity_id   UUID REFERENCES identities(id),
    chosen_identity_id      UUID REFERENCES identities(id),
    top_similarity          FLOAT NOT NULL,
    embedding_snapshot      VECTOR(512),
    candidates              JSONB DEFAULT '[]',
    image_url               TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',  -- pending | applied | discarded
    correction_type         TEXT,                              -- confirm | reassign | reject
    reviewer_id             UUID REFERENCES auth_users(id),
    new_embedding_id        UUID REFERENCES face_embeddings(id) ON DELETE SET NULL,
    notes                   TEXT,
    applied_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_correction_status ON correction_candidates(status);
CREATE INDEX IF NOT EXISTS idx_correction_tenant ON correction_candidates(tenant_id);

ALTER TABLE correction_candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_correction" ON correction_candidates
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: drift_reports (historique des analyses de drift)
-- ============================================================
CREATE TABLE IF NOT EXISTS drift_reports (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    identity_id              UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    tenant_id                UUID REFERENCES tenants(id) ON DELETE CASCADE,
    n_baseline               INT,
    n_recent                 INT,
    baseline_cohesion        FLOAT,
    recent_vs_baseline_sim   FLOAT,
    drift_detected           BOOLEAN,
    threshold                FLOAT,
    action_taken             TEXT,
    created_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_identity ON drift_reports(identity_id);
CREATE INDEX IF NOT EXISTS idx_drift_created  ON drift_reports(created_at DESC);

ALTER TABLE drift_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_drift" ON drift_reports
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: tenant_usage_daily (compteurs pour quotas)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_usage_daily (
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    day             DATE NOT NULL,
    recognitions    INT NOT NULL DEFAULT 0,
    kyc_sessions    INT NOT NULL DEFAULT 0,
    access_checks   INT NOT NULL DEFAULT 0,
    webhook_deliveries INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, day)
);

ALTER TABLE tenant_usage_daily ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_usage" ON tenant_usage_daily
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- RPC: search_voice (recherche vocale 1:N)
-- ============================================================
CREATE OR REPLACE FUNCTION search_voice(
    query_embedding VECTOR(256),
    match_threshold FLOAT DEFAULT 0.7,
    match_count     INT   DEFAULT 5,
    p_tenant_id     UUID  DEFAULT NULL
)
RETURNS TABLE (
    identity_id   UUID,
    full_name     TEXT,
    similarity    FLOAT,
    voice_embedding_id UUID
)
LANGUAGE sql STABLE AS $$
    SELECT
        i.id,
        i.full_name,
        1 - (ve.embedding <=> query_embedding) AS similarity,
        ve.id
    FROM voice_embeddings ve
    JOIN identities i ON ve.identity_id = i.id
    WHERE i.status = 'active'
      AND (p_tenant_id IS NULL OR i.tenant_id = p_tenant_id)
      AND ve.embedding IS NOT NULL
      AND 1 - (ve.embedding <=> query_embedding) > match_threshold
    ORDER BY ve.embedding <=> query_embedding
    LIMIT match_count;
$$;


-- ============================================================
-- RPC: increment_tenant_usage
-- ============================================================
CREATE OR REPLACE FUNCTION increment_tenant_usage(
    p_tenant_id   UUID,
    p_counter     TEXT,                    -- recognitions | kyc_sessions | access_checks
    p_amount      INT DEFAULT 1
) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE
    new_value INT;
BEGIN
    INSERT INTO tenant_usage_daily (tenant_id, day)
    VALUES (p_tenant_id, CURRENT_DATE)
    ON CONFLICT (tenant_id, day) DO NOTHING;

    IF p_counter = 'recognitions' THEN
        UPDATE tenant_usage_daily SET recognitions = recognitions + p_amount
        WHERE tenant_id = p_tenant_id AND day = CURRENT_DATE
        RETURNING recognitions INTO new_value;
    ELSIF p_counter = 'kyc_sessions' THEN
        UPDATE tenant_usage_daily SET kyc_sessions = kyc_sessions + p_amount
        WHERE tenant_id = p_tenant_id AND day = CURRENT_DATE
        RETURNING kyc_sessions INTO new_value;
    ELSIF p_counter = 'access_checks' THEN
        UPDATE tenant_usage_daily SET access_checks = access_checks + p_amount
        WHERE tenant_id = p_tenant_id AND day = CURRENT_DATE
        RETURNING access_checks INTO new_value;
    ELSIF p_counter = 'webhook_deliveries' THEN
        UPDATE tenant_usage_daily SET webhook_deliveries = webhook_deliveries + p_amount
        WHERE tenant_id = p_tenant_id AND day = CURRENT_DATE
        RETURNING webhook_deliveries INTO new_value;
    END IF;

    RETURN COALESCE(new_value, 0);
END;
$$;


-- ============================================================
-- VIEW: tenant_overview (analytics par tenant)
-- ============================================================
CREATE OR REPLACE VIEW tenant_overview AS
SELECT
    t.id                                  AS tenant_id,
    t.code,
    t.name,
    t.plan,
    t.is_active,
    (SELECT COUNT(*) FROM identities WHERE tenant_id = t.id)               AS identities_count,
    (SELECT COUNT(*) FROM face_embeddings WHERE tenant_id = t.id)          AS embeddings_count,
    (SELECT COUNT(*) FROM recognition_events
       WHERE tenant_id = t.id AND created_at > NOW() - INTERVAL '1 day')   AS recognitions_24h,
    (SELECT COUNT(*) FROM webhooks WHERE tenant_id = t.id AND is_active)   AS webhooks_active
FROM tenants t;
