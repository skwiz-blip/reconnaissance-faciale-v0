/** Types miroirs des schémas Pydantic backend. */

export interface User {
  user_id: string;
  email?: string;
  role: "admin" | "operator" | "viewer";
}

export interface TokenResponse {
  access_token:  string;
  refresh_token: string;
  token_type:    string;
  expires_in:    number;
  user_id:       string;
  role:          string;
}

export interface Identity {
  id:          string;
  full_name:   string;
  email?:      string;
  role:        "user" | "admin" | "vip" | "blocked";
  status:      "active" | "inactive" | "blocked";
  department?: string;
  created_at:  string;
}

export interface UnknownFace {
  id:            string;
  temp_id:       string;
  appearances:   number;
  first_seen_at: string;
  last_seen_at:  string;
  location?:     string;
  cluster_id?:   string;
  image_url?:    string;
}

export interface Cluster {
  cluster_id:        string;
  cluster_size:      number;
  total_appearances: number;
  first_seen_at:     string;
  last_seen_at:      string;
  sample_temp_id?:   string;
  sample_image_url?: string;
}

export interface Zone {
  id:             string;
  code:           string;
  name:           string;
  description?:   string;
  security_level: "public" | "restricted" | "secured" | "classified";
  is_active:      boolean;
  created_at:     string;
}

export interface AccessPolicy {
  id:                       string;
  zone_id:                  string;
  name:                     string;
  priority:                 number;
  allowed_roles:            string[];
  allowed_days?:            string[];
  start_time?:              string;
  end_time?:                string;
  require_liveness:         boolean;
  min_similarity?:          number;
  alert_below_similarity?:  number;
  max_per_minute?:          number;
  is_active:                boolean;
  created_at:               string;
}

export interface AccessLogEntry {
  id:              string;
  created_at:      string;
  decision:        "granted" | "denied" | "alert";
  reason?:         string;
  access_point:    string;
  zone?:           string;
  identity_id?:    string;
  identity_name?:  string;
  identity_role?:  string;
  confidence?:     number;
  liveness_score?: number;
  camera_id?:      string;
}

export interface KYCSession {
  session_id:        string;
  decision:          "approved" | "review" | "rejected" | "pending" | "processing";
  confidence:        number;
  face_match_score?: number;
  liveness_score?:   number;
  risk_score?:       number;
  classified_type?:  string;
  declared_type?:    string;
  fraud_flags:       string[];
  reasons:           string[];
  mrz?:              Record<string, unknown> | null;
  ocr_fields?:       Record<string, unknown> | null;
}

export interface AuditLog {
  id:           string;
  actor_id?:    string;
  actor_role?:  string;
  action:       string;
  target_type?: string;
  target_id?:   string;
  ip_address?:  string;
  user_agent?:  string;
  metadata?:    Record<string, unknown>;
  created_at:   string;
}

export interface StatsResponse {
  identities:       number;
  embeddings:       number;
  total_events:     number;
  pending_unknowns: number;
  faiss: {
    size:   number;
    ready:  boolean;
    backend: string;
    last_sync_ago_s?: number;
    identities?: number;
  };
  redis_enabled: boolean;
}

export interface RecognizeMatch {
  identity_id: string;
  full_name:   string;
  role:        string;
  similarity:  number;
}

export interface WsCameraResult {
  type: "result";
  frame_id: number;
  event_type: "recognized" | "unknown" | "rejected" | "spoof_detected";
  face_count: number;
  is_live: boolean;
  liveness_score: number;
  quality_score: number;
  processing_ms: number;
  matches: RecognizeMatch[];
  unknown_id?: string | null;
  error?: string | null;
}
