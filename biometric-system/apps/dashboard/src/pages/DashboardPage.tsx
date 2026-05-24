import { useQuery } from "@tanstack/react-query";
import { Users, Database, UserX, Activity, Shield, AlertTriangle } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";
import StatCard from "@/components/StatCard";
import { statsApi, accessApi } from "@/api/endpoints";

export default function DashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ["stats"], queryFn: statsApi.stats, refetchInterval: 15_000,
  });
  const { data: logs = [] } = useQuery({
    queryKey: ["access-logs", 50],
    queryFn:  () => accessApi.logs(50),
    refetchInterval: 10_000,
  });

  const decisions = logs.reduce<Record<string, number>>((acc, l) => {
    acc[l.decision] = (acc[l.decision] ?? 0) + 1;
    return acc;
  }, {});
  const chartData = [
    { name: "Granted", value: decisions.granted ?? 0 },
    { name: "Denied",  value: decisions.denied ?? 0 },
    { name: "Alert",   value: decisions.alert ?? 0 },
  ];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Vue d'ensemble</h1>
        <p className="text-sm text-slate-400">
          Système biométrique · {stats?.faiss?.backend ?? "FAISS"} ·{" "}
          Redis: {stats?.redis_enabled ? "actif" : "désactivé"}
        </p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Identités"   value={stats?.identities ?? "—"} icon={Users} />
        <StatCard label="Embeddings"  value={stats?.embeddings ?? "—"} icon={Database}
                  hint={stats?.faiss ? `index: ${stats.faiss.size}` : undefined} />
        <StatCard label="Inconnus pendants" value={stats?.pending_unknowns ?? "—"}
                  icon={UserX} accent="amber" />
        <StatCard label="Évén. reco totaux" value={stats?.total_events ?? "—"}
                  icon={Activity} accent="emerald" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Décisions d'accès */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold flex items-center gap-2">
              <Shield className="h-4 w-4 text-brand-300" /> Décisions d'accès (50 dernières)
            </h2>
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
                  labelStyle={{ color: "#cbd5e1" }}
                />
                <Bar dataKey="value" fill="#6366f1" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Récents événements */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-300" /> Événements récents
            </h2>
          </div>
          <div className="max-h-64 overflow-y-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Quand</th><th>Identité</th><th>Zone</th><th>Décision</th>
                </tr>
              </thead>
              <tbody>
                {logs.slice(0, 10).map(log => (
                  <tr key={log.id}>
                    <td className="text-xs text-slate-400">
                      {formatDistanceToNow(new Date(log.created_at), { addSuffix: true, locale: fr })}
                    </td>
                    <td>{log.identity_name ?? <span className="text-slate-500">inconnu</span>}</td>
                    <td className="text-slate-400">{log.zone ?? "—"}</td>
                    <td>
                      <span className={
                        log.decision === "granted" ? "badge-green" :
                        log.decision === "alert"   ? "badge-amber" :
                        "badge-red"
                      }>{log.decision}</span>
                    </td>
                  </tr>
                ))}
                {logs.length === 0 && (
                  <tr><td colSpan={4} className="text-center text-slate-500 py-6">Aucun événement</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
