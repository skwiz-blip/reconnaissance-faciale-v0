-- ============================================================
-- BIOMETRIC SYSTEM — Phase 2: Auth + Clusters + Audit
-- À exécuter dans le SQL Editor Supabase APRÈS 001_initial_schema.sql
-- ============================================================

-- ============================================================
-- TABLE: auth_users
-- Comptes admin/opérateurs (distincts des "identities" biométriques)
-- ============================================================
CREATE TABLE IF NOT EXISTS auth_users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'operator',  -- admin | operator | viewer
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT auth_users_role_check
        CHECK (role IN ('admin', 'operator', 'viewer'))
);

CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(LOWER(email));

DROP TRIGGER IF EXISTS trg_auth_users_updated ON auth_users;
CREATE TRIGGER trg_auth_users_updated
    BEFORE UPDATE ON auth_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE auth_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_auth_users" ON auth_users
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: audit_logs
-- Trace toutes les actions sensibles (création/suppression identités,
-- résolution inconnus, modifications de rôles, etc.)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id        UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    actor_role      TEXT,
    action          TEXT NOT NULL,            -- identity.create | identity.delete | unknown.resolve | cluster.merge | ...
    target_type     TEXT,                     -- identity | unknown | cluster | embedding | auth_user
    target_id       TEXT,
    ip_address      TEXT,
    user_agent      TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_actor   ON audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_audit" ON audit_logs
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);


-- ============================================================
-- TABLE: unknown_clusters (vue dénormalisée des clusters)
-- ============================================================
-- (Pas une table physique: vue agrégée pour list_clusters RPC)


-- ============================================================
-- INDEX additionnel pour le clustering
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_unknown_cluster
    ON unknown_faces(cluster_id) WHERE resolved = FALSE AND cluster_id IS NOT NULL;


-- ============================================================
-- RPC: list_clusters
-- Retourne les clusters d'inconnus avec leur taille + représentant
-- ============================================================
CREATE OR REPLACE FUNCTION list_clusters(max_count INT DEFAULT 50)
RETURNS TABLE (
    cluster_id      TEXT,
    cluster_size    INT,
    total_appearances INT,
    first_seen_at   TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ,
    sample_temp_id  TEXT,
    sample_image_url TEXT
)
LANGUAGE sql STABLE AS $$
    WITH cluster_agg AS (
        SELECT
            cluster_id,
            COUNT(*)::INT             AS cluster_size,
            SUM(appearances)::INT     AS total_appearances,
            MIN(first_seen_at)        AS first_seen_at,
            MAX(last_seen_at)         AS last_seen_at
        FROM unknown_faces
        WHERE resolved = FALSE
          AND cluster_id IS NOT NULL
        GROUP BY cluster_id
    ),
    sample AS (
        SELECT DISTINCT ON (cluster_id)
            cluster_id, temp_id, image_url
        FROM unknown_faces
        WHERE resolved = FALSE AND cluster_id IS NOT NULL
        ORDER BY cluster_id, appearances DESC
    )
    SELECT
        c.cluster_id,
        c.cluster_size,
        c.total_appearances,
        c.first_seen_at,
        c.last_seen_at,
        s.temp_id,
        s.image_url
    FROM cluster_agg c
    LEFT JOIN sample s USING (cluster_id)
    ORDER BY c.cluster_size DESC, c.last_seen_at DESC
    LIMIT max_count;
$$;


-- ============================================================
-- RPC: increment_unknown_appearances (referenced from existing code)
-- ============================================================
CREATE OR REPLACE FUNCTION increment_unknown_appearances(unknown_id UUID)
RETURNS VOID
LANGUAGE sql AS $$
    UPDATE unknown_faces
    SET appearances = appearances + 1,
        last_seen_at = NOW()
    WHERE id = unknown_id;
$$;


-- ============================================================
-- RPC: search_face avec filtre cluster (Phase 2)
-- ============================================================
CREATE OR REPLACE FUNCTION search_face_in_cluster(
    query_embedding VECTOR(512),
    target_cluster_id TEXT,
    match_threshold FLOAT DEFAULT 0.6,
    match_count     INT   DEFAULT 5
)
RETURNS TABLE (
    unknown_id      UUID,
    temp_id         TEXT,
    similarity      FLOAT,
    appearances     INT
)
LANGUAGE sql STABLE AS $$
    SELECT
        id,
        temp_id,
        1 - (embedding <=> query_embedding) AS similarity,
        appearances
    FROM unknown_faces
    WHERE resolved = FALSE
      AND cluster_id = target_cluster_id
      AND 1 - (embedding <=> query_embedding) > match_threshold
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
