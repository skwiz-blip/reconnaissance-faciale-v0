import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { auditApi } from "@/api/endpoints";

export default function AuditPage() {
  const [action, setAction] = useState("");
  const { data: logs = [] } = useQuery({
    queryKey: ["audit", action],
    queryFn:  () => auditApi.list(200, action || undefined),
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Audit logs</h1>
        <p className="text-sm text-slate-400">Toutes les actions sensibles (mutations sur identités, KYC, accès…)</p>
      </header>

      <div className="card space-y-3">
        <input
          className="input max-w-md"
          placeholder="Filtrer par action (ex: identities.delete, kyc.* …)"
          value={action} onChange={e => setAction(e.target.value)}
        />
        <table className="table">
          <thead>
            <tr>
              <th>Quand</th><th>Acteur</th><th>Rôle</th>
              <th>Action</th><th>Cible</th><th>IP</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id}>
                <td className="text-xs text-slate-400">
                  {format(new Date(l.created_at), "dd/MM HH:mm:ss")}
                </td>
                <td className="font-mono text-xs">{l.actor_id?.slice(0, 8) ?? "—"}</td>
                <td><span className="badge-slate">{l.actor_role ?? "?"}</span></td>
                <td className="font-mono text-xs">{l.action}</td>
                <td className="text-slate-400 text-xs">
                  {l.target_type} · {l.target_id?.slice(0, 8) ?? "—"}
                </td>
                <td className="text-xs text-slate-500">{l.ip_address ?? "—"}</td>
                <td>
                  {(l.metadata as any)?.status ? (
                    <span className={
                      (l.metadata as any).status < 300 ? "badge-green" : "badge-red"
                    }>{(l.metadata as any).status}</span>
                  ) : "—"}
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr><td colSpan={7} className="text-center py-6 text-slate-500">Aucun log</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
