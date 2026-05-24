/**
 * Axios client avec interceptor JWT.
 * - Attache l'access_token sur chaque requête
 * - Tente automatiquement un /auth/refresh sur 401
 * - Si le refresh échoue, vide le storage et redirige vers /login
 */
import axios, { AxiosError, AxiosRequestConfig } from "axios";

const BASE_URL = import.meta.env.VITE_API_URL ?? "/";

export const STORAGE_KEYS = {
  access:  "bio.access",
  refresh: "bio.refresh",
  user:    "bio.user",
} as const;

export const tokenStorage = {
  getAccess:  () => localStorage.getItem(STORAGE_KEYS.access),
  getRefresh: () => localStorage.getItem(STORAGE_KEYS.refresh),
  set: (access: string, refresh: string, user: unknown) => {
    localStorage.setItem(STORAGE_KEYS.access, access);
    localStorage.setItem(STORAGE_KEYS.refresh, refresh);
    localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user));
  },
  clear: () => {
    localStorage.removeItem(STORAGE_KEYS.access);
    localStorage.removeItem(STORAGE_KEYS.refresh);
    localStorage.removeItem(STORAGE_KEYS.user);
  },
  getUser: () => {
    const raw = localStorage.getItem(STORAGE_KEYS.user);
    return raw ? JSON.parse(raw) : null;
  },
};

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  const token = tokenStorage.getAccess();
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Refresh logic — éviter les requêtes parallèles qui déclencheraient N refresh
let refreshPromise: Promise<string> | null = null;

async function performRefresh(): Promise<string> {
  const refresh = tokenStorage.getRefresh();
  if (!refresh) throw new Error("Pas de refresh token");

  const res = await axios.post(
    `${BASE_URL}api/v1/auth/refresh`,
    { refresh_token: refresh },
    { headers: { "Content-Type": "application/json" } }
  );
  const data = res.data as {
    access_token: string; refresh_token: string;
    user_id: string; role: string;
  };
  tokenStorage.set(data.access_token, data.refresh_token, {
    user_id: data.user_id, role: data.role,
  });
  return data.access_token;
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };
    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes("/auth/")
    ) {
      original._retry = true;
      try {
        const newToken = await (refreshPromise ?? (refreshPromise = performRefresh()));
        refreshPromise = null;
        if (original.headers) (original.headers as any).Authorization = `Bearer ${newToken}`;
        return api.request(original);
      } catch {
        refreshPromise = null;
        tokenStorage.clear();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);
