import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { tokenStorage } from "@/api/client";
import { authApi } from "@/api/endpoints";
import type { User } from "@/api/types";

interface AuthState {
  user:   User | null;
  ready:  boolean;
  login:  (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(() => tokenStorage.getUser());
  const [ready, setReady] = useState(false);

  // Validation initiale: tente un /auth/me pour vérifier la fraîcheur du token
  useEffect(() => {
    const token = tokenStorage.getAccess();
    if (!token) {
      setReady(true);
      return;
    }
    authApi.me()
      .then((me) => { setUser(me); })
      .catch(() => { tokenStorage.clear(); setUser(null); })
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password);
    tokenStorage.set(data.access_token, data.refresh_token, {
      user_id: data.user_id, role: data.role,
    });
    const me = await authApi.me();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try { await authApi.logout(); } catch { /* ignore */ }
    tokenStorage.clear();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, login, logout }), [user, ready, login, logout]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth doit être utilisé dans <AuthProvider>");
  return ctx;
}
