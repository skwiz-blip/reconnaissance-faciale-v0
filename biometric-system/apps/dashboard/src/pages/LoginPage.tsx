import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Fingerprint } from "lucide-react";
import toast from "react-hot-toast";
import { useAuth } from "@/auth/AuthContext";
import { authApi } from "@/api/endpoints";
import { tokenStorage } from "@/api/client";

export default function LoginPage() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [mode, setMode]         = useState<"login" | "register">("login");
  const [loading, setLoading]   = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === "register") {
        const data = await authApi.register({ email, password, full_name: fullName });
        tokenStorage.set(data.access_token, data.refresh_token, {
          user_id: data.user_id, role: data.role,
        });
        toast.success(`Compte créé · rôle ${data.role}`);
      } else {
        await login(email, password);
        toast.success("Connecté");
      }
      nav("/", { replace: true });
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Échec de l'authentification");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-brand-900/40 p-4">
      <div className="card w-full max-w-md">
        <div className="flex flex-col items-center gap-2 mb-6">
          <Fingerprint className="h-12 w-12 text-brand-500" />
          <h1 className="text-xl font-semibold">Biometric Console</h1>
          <p className="text-sm text-slate-400">
            {mode === "login" ? "Connexion administrateur" : "Création de compte"}
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          {mode === "register" && (
            <div>
              <label className="label">Nom complet</label>
              <input className="input" required minLength={2}
                value={fullName} onChange={e => setFullName(e.target.value)} />
            </div>
          )}
          <div>
            <label className="label">Email</label>
            <input type="email" className="input" required autoComplete="email"
              value={email} onChange={e => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label">Mot de passe</label>
            <input type="password" className="input" required minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password} onChange={e => setPassword(e.target.value)} />
          </div>
          <button disabled={loading} className="btn-primary w-full justify-center mt-2">
            {loading ? "…" : mode === "login" ? "Se connecter" : "Créer le compte"}
          </button>
        </form>

        <button
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="mt-4 w-full text-xs text-slate-400 hover:text-slate-200"
        >
          {mode === "login"
            ? "Pas de compte ? Créer le premier compte (auto admin)"
            : "Déjà un compte ? Se connecter"}
        </button>
      </div>
    </div>
  );
}
