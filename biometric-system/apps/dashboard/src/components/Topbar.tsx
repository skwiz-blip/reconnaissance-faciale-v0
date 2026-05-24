import { useQuery } from "@tanstack/react-query";
import { LogOut, Activity } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { statsApi } from "@/api/endpoints";

export default function Topbar() {
  const { user, logout } = useAuth();
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn:  statsApi.health,
    refetchInterval: 30_000,
  });

  const isHealthy = health?.status === "healthy";

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/40 px-6 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <Activity className={isHealthy ? "h-4 w-4 text-emerald-400" : "h-4 w-4 text-amber-400"} />
        <span className="text-xs text-slate-400">
          Statut: <span className={isHealthy ? "text-emerald-300" : "text-amber-300"}>
            {health?.status ?? "…"}
          </span>
        </span>
        {health?.checks?.faiss && (
          <span className="text-xs text-slate-500">FAISS: {String(health.checks.faiss)}</span>
        )}
      </div>
      <div className="flex items-center gap-4">
        <div className="text-right">
          <div className="text-sm text-slate-200">{user?.email ?? user?.user_id}</div>
          <div className="text-xs text-slate-500 uppercase">{user?.role}</div>
        </div>
        <button onClick={logout} className="btn-secondary" title="Déconnexion">
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
