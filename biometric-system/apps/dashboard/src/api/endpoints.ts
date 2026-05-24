/** Wrappers minces sur les endpoints backend. */
import { api } from "./client";
import type {
  Identity, UnknownFace, Cluster, Zone, AccessPolicy,
  AccessLogEntry, KYCSession, AuditLog, StatsResponse,
} from "./types";

// ---------- Auth ----------
export const authApi = {
  login:    (email: string, password: string) =>
    api.post("/api/v1/auth/login", { email, password }).then(r => r.data),
  register: (payload: { email: string; password: string; full_name: string; role?: string }) =>
    api.post("/api/v1/auth/register", payload).then(r => r.data),
  me:       () => api.get("/api/v1/auth/me").then(r => r.data),
  logout:   () => api.post("/api/v1/auth/logout").then(r => r.data),
};

// ---------- Stats / Health ----------
export const statsApi = {
  stats:  () => api.get<StatsResponse>("/api/v1/stats").then(r => r.data),
  health: () => api.get("/health").then(r => r.data),
};

// ---------- Identités ----------
export const identitiesApi = {
  list: (limit = 50, offset = 0) =>
    api.get<{ items: Identity[]; total: number }>(
      `/api/v1/identities?limit=${limit}&offset=${offset}`
    ).then(r => r.data),
  get: (id: string) => api.get<Identity>(`/api/v1/identities/${id}`).then(r => r.data),
  create: (payload: Partial<Identity>) =>
    api.post<Identity>("/api/v1/identities", payload).then(r => r.data),
  update: (id: string, payload: Partial<Identity>) =>
    api.patch<Identity>(`/api/v1/identities/${id}`, payload).then(r => r.data),
  remove: (id: string) =>
    api.delete(`/api/v1/identities/${id}`).then(r => r.data),
  enroll: async (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post(`/api/v1/identities/${id}/enroll/upload`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    }).then(r => r.data);
  },
  listEmbeddings: (id: string) =>
    api.get(`/api/v1/identities/${id}/embeddings`).then(r => r.data),
};

// ---------- Reco ----------
export const recognizeApi = {
  recognizeFile: async (file: File, checkLiveness = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("check_liveness", String(checkLiveness));
    return api.post("/api/v1/recognize/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
    }).then(r => r.data);
  },
};

// ---------- Unknowns ----------
export const unknownsApi = {
  list: (limit = 100) =>
    api.get<UnknownFace[]>(`/api/v1/unknowns?limit=${limit}`).then(r => r.data),
  resolve: (id: string, identityId?: string, newIdentity?: Partial<Identity>) =>
    api.post(`/api/v1/unknowns/${id}/resolve`, {
      unknown_id: id,
      identity_id: identityId,
      new_identity: newIdentity,
    }).then(r => r.data),
};

// ---------- Clusters ----------
export const clustersApi = {
  list: () => api.get<Cluster[]>("/api/v1/clusters").then(r => r.data),
  run: (similarity = 0.65, minSamples = 2) =>
    api.post("/api/v1/clusters/run", {
      similarity_threshold: similarity,
      min_samples: minSamples,
      batch_limit: 5000,
    }).then(r => r.data),
  faces: (clusterId: string) =>
    api.get<UnknownFace[]>(`/api/v1/clusters/${clusterId}/faces`).then(r => r.data),
  merge: (clusterId: string, identityId: string) =>
    api.post(`/api/v1/clusters/${clusterId}/merge?identity_id=${identityId}`).then(r => r.data),
};

// ---------- Access ----------
export const accessApi = {
  check: (payload: {
    image_base64: string; zone_code: string; access_point: string;
    camera_id?: string; check_liveness?: boolean;
  }) => api.post("/api/v1/access/check", payload).then(r => r.data),

  listZones: () => api.get<Zone[]>("/api/v1/access/zones").then(r => r.data),
  createZone: (z: Partial<Zone>) => api.post<Zone>("/api/v1/access/zones", z).then(r => r.data),
  updateZone: (id: string, z: Partial<Zone>) =>
    api.patch<Zone>(`/api/v1/access/zones/${id}`, z).then(r => r.data),
  deleteZone: (id: string) => api.delete(`/api/v1/access/zones/${id}`).then(r => r.data),

  listPolicies: (zoneId?: string) =>
    api.get<AccessPolicy[]>(`/api/v1/access/policies${zoneId ? `?zone_id=${zoneId}` : ""}`).then(r => r.data),
  createPolicy: (p: Partial<AccessPolicy>) =>
    api.post<AccessPolicy>("/api/v1/access/policies", p).then(r => r.data),
  deletePolicy: (id: string) =>
    api.delete(`/api/v1/access/policies/${id}`).then(r => r.data),

  logs: (limit = 100, decision?: string, zone?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (decision) params.set("decision", decision);
    if (zone) params.set("zone", zone);
    return api.get<AccessLogEntry[]>(`/api/v1/access/logs?${params}`).then(r => r.data);
  },
};

// ---------- KYC ----------
export const kycApi = {
  start: (docType: string, issueChallenge = true, identityId?: string) =>
    api.post("/api/v1/kyc/sessions", {
      doc_type: docType, issue_challenge: issueChallenge, identity_id: identityId,
    }).then(r => r.data),
  submit: (sessionToken: string, selfieBase64: string, docBase64: string) =>
    api.post("/api/v1/kyc/sessions/submit", {
      session_token: sessionToken,
      selfie_base64: selfieBase64,
      document_base64: docBase64,
    }).then(r => r.data),
  get: (sessionId: string) =>
    api.get<KYCSession>(`/api/v1/kyc/sessions/${sessionId}`).then(r => r.data),
};

// ---------- Audit ----------
export const auditApi = {
  list: (limit = 100, action?: string, actorId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (action) params.set("action", action);
    if (actorId) params.set("actor_id", actorId);
    return api.get<AuditLog[]>(`/api/v1/audit?${params}`).then(r => r.data);
  },
};
