-- ============================================================
-- BIOMETRIC SYSTEM — Phase 3: KYC + Access Control + Liveness Challenges
-- À exécuter dans le SQL Editor Supabase APRÈS 002_phase2_auth_clusters.sql
-- ============================================================

-- ============================================================
-- TABLE: zones
-- Zones physiques ou logiques contrôlées (entrée, salle serveur, parking…)
-- ============================================================
CREATE TABLE IF NOT EXISTS zones (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code            TEXT UNIQUE NOT NULL,           -- ex: 'lobby', 'server_room', 'parking_b1'
    name            TEXT NOT NULL,
    description     TEXT,
    security_level  TEXT NOT NULL DEFAULT 'public', -- public | restricted | secured | classified
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT zones_security_check
        CHECK (security_level IN ('public', 'restricted', 'secured', 'classified'))
);

CREATE INDEX IF NOT EXISTS idx_zones_code ON zones(code);

DROP TRIGGER IF EXISTS trg_zones_updated ON zones;
CREATE TRIGGER trg_zones_updated
    BEFORE UPDATE ON zones FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE zones ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_zones" ON zones
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: access_policies
-- Politique RBAC + horaire + sécurité par zone
-- ============================================================
CREATE TABLE IF NOT EXISTS access_policies (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zone_id                  UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    name                     TEXT NOT NULL,
    priority                 INT NOT NULL DEFAULT 100,       -- évaluation décroissante
    allowed_roles            TEXT[] NOT NULL DEFAULT '{}',   -- ex: {'admin','vip'}
    allowed_days             TEXT[] DEFAULT NULL,            -- {'mon','tue',…} NULL = tous
    start_time               TEXT DEFAULT NULL,              -- 'HH:MM' UTC
    end_time                 TEXT DEFAULT NULL,
    require_liveness         BOOLEAN NOT NULL DEFAULT FALSE,
    min_similarity           FLOAT,                          -- ex: 0.75
    alert_below_similarity   FLOAT,                          -- alerte (granted) si <
    max_per_minute           INT,                            -- anti-tailgating
    is_active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policies_zone ON access_policies(zone_id);
CREATE INDEX IF NOT EXISTS idx_policies_priority ON access_policies(priority DESC) WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS trg_policies_updated ON access_policies;
CREATE TRIGGER trg_policies_updated
    BEFORE UPDATE ON access_policies FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE access_policies ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_policies" ON access_policies
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: liveness_challenges
-- Défis (blink/turn/smile) émis et leur résolution
-- ============================================================
CREATE TABLE IF NOT EXISTS liveness_challenges (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    challenge_id    TEXT UNIQUE NOT NULL,         -- ID public envoyé au client
    action          TEXT NOT NULL,                -- blink | turn_left | …
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | passed | failed | expired
    issued_to       UUID,                         -- identity_id si connue
    issued_for      TEXT,                         -- contexte: login | kyc | access
    progress        FLOAT NOT NULL DEFAULT 0.0,
    frames_received INT NOT NULL DEFAULT 0,
    issued_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_challenges_id      ON liveness_challenges(challenge_id);
CREATE INDEX IF NOT EXISTS idx_challenges_status  ON liveness_challenges(status);
CREATE INDEX IF NOT EXISTS idx_challenges_expires ON liveness_challenges(expires_at);

ALTER TABLE liveness_challenges ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_challenges" ON liveness_challenges
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- EXTENSION TABLE: kyc_sessions
-- Ajout des colonnes Phase 3 (idempotent)
-- ============================================================
ALTER TABLE kyc_sessions
    ADD COLUMN IF NOT EXISTS classified_type TEXT,
    ADD COLUMN IF NOT EXISTS mrz_data        JSONB,
    ADD COLUMN IF NOT EXISTS mrz_checks      JSONB,
    ADD COLUMN IF NOT EXISTS ocr_data        JSONB,
    ADD COLUMN IF NOT EXISTS risk_score      FLOAT DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS decision        TEXT,
    ADD COLUMN IF NOT EXISTS confidence      FLOAT,
    ADD COLUMN IF NOT EXISTS reasons         JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS challenge_id    TEXT REFERENCES liveness_challenges(challenge_id);


-- ============================================================
-- TABLE: access_points
-- Mappe access_point ↔ zone (un access_point appartient à 1 zone)
-- ============================================================
CREATE TABLE IF NOT EXISTS access_points (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    zone_id         UUID NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    camera_id       UUID REFERENCES cameras(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_points_zone   ON access_points(zone_id);
CREATE INDEX IF NOT EXISTS idx_access_points_camera ON access_points(camera_id);

ALTER TABLE access_points ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_access_points" ON access_points
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- DONNÉES SEED (zones de démo)
-- ============================================================
INSERT INTO zones (code, name, description, security_level) VALUES
    ('lobby',        'Lobby principal',       'Accès libre journée',  'public'),
    ('office',       'Espaces bureaux',       'Personnel uniquement', 'restricted'),
    ('server_room',  'Salle serveurs',        'Admin + DSI',          'secured'),
    ('vault',        'Zone classifiée',       'Accès très restreint', 'classified')
ON CONFLICT (code) DO NOTHING;

-- Politiques par défaut (admin uniquement sur zones secured/classified)
INSERT INTO access_policies (zone_id, name, priority, allowed_roles, require_liveness, min_similarity)
SELECT id, 'admin_only_24x7', 200, ARRAY['admin'], TRUE, 0.75
FROM zones WHERE code IN ('server_room', 'vault')
ON CONFLICT DO NOTHING;

INSERT INTO access_policies (zone_id, name, priority, allowed_roles,
                             allowed_days, start_time, end_time, min_similarity)
SELECT id, 'office_workdays', 100,
       ARRAY['admin', 'user', 'vip'],
       ARRAY['mon','tue','wed','thu','fri'],
       '07:00', '20:00', 0.65
FROM zones WHERE code = 'office'
ON CONFLICT DO NOTHING;

INSERT INTO access_policies (zone_id, name, priority, allowed_roles, min_similarity)
SELECT id, 'lobby_all', 50, ARRAY['admin','user','vip','operator'], 0.55
FROM zones WHERE code = 'lobby'
ON CONFLICT DO NOTHING;


-- ============================================================
-- RPC: cleanup_expired_challenges
-- ============================================================
CREATE OR REPLACE FUNCTION cleanup_expired_challenges()
RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE
    n INT;
BEGIN
    UPDATE liveness_challenges
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at < NOW()
    RETURNING 1 INTO n;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;


-- ============================================================
-- VIEW: access_summary (analytics)
-- ============================================================
CREATE OR REPLACE VIEW access_summary AS
SELECT
    al.id,
    al.created_at,
    al.decision,
    al.reason,
    al.access_point,
    al.zone,
    al.identity_id,
    i.full_name AS identity_name,
    i.role      AS identity_role,
    re.confidence,
    re.liveness_score,
    re.camera_id
FROM access_logs al
LEFT JOIN identities          i  ON i.id  = al.identity_id
LEFT JOIN recognition_events  re ON re.id = al.event_id;
