import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { accessApi } from "@/api/endpoints";

export default function AccessLogsTab() {
  const [decision, setDecision] = useState<string>("");
  const [zone, setZone] = useState<string>("");
  const { data: logs = [] } = useQuery({
    queryKey: ["access-logs-tab", decision, zone],
    queryFn:  () => accessApi.logs(200, decision || undefined, zone || undefined),
    refetchInterval: 10_000,
  });

  return (
    <div className="card space-y-4">
      <div className="flex gap-3">
        <select className="input max-w-xs" value={decision} onChange={e => setDecision(e.target.value)}>
          <option value="">Toutes décisions</option>
          <option value="granted">granted</option>
          <option value="denied">denied</option>
          <option value="alert">alert</option>
        </select>
        <input className="input max-w-xs" placeholder="Filtrer zone (code)"
               value={zone} onChange={e => setZone(e.target.value)} />
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Quand</th><th>Identité</th><th>Rôle</th>
            <th>Zone</th><th>Point</th><th>Décision</th>
            <th>Score</th><th>Raison</th>
          </tr>
        </thead>
        <tbody>
          {logs.map(l => (
            <tr key={l.id}>
              <td className="text-xs text-slate-400">
                {format(new Date(l.created_at), "dd/MM HH:mm:ss")}
              </td>
              <td>{l.identity_name ?? <span className="text-slate-500 italic">inconnu</span>}</td>
              <td className="text-slate-400">{l.identity_role ?? "—"}</td>
              <td>{l.zone ?? "—"}</td>
              <td className="text-slate-400">{l.access_point}</td>
              <td>
                <span className={
                  l.decision === "granted" ? "badge-green" :
                  l.decision === "alert"   ? "badge-amber" :
                  "badge-red"
                }>{l.decision}</span>
              </td>
              <td className="text-xs">
                {l.confidence != null ? `${(l.confidence * 100).toFixed(1)}%` : "—"}
              </td>
              <td className="text-xs text-slate-400 truncate max-w-xs">{l.reason ?? "—"}</td>
            </tr>
          ))}
          {logs.length === 0 && (
            <tr><td colSpan={8} className="text-center py-6 text-slate-500">Aucun log</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
