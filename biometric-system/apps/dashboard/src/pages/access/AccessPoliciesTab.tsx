import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { accessApi } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";
import type { AccessPolicy } from "@/api/types";

const ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const ALL_ROLES = ["admin", "operator", "user", "vip"] as const;

export default function AccessPoliciesTab() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const { data: zones = [] } = useQuery({ queryKey: ["zones"], queryFn: accessApi.listZones });
  const [zoneFilter, setZoneFilter] = useState("");
  const { data: policies = [] } = useQuery({
    queryKey: ["policies", zoneFilter],
    queryFn:  () => accessApi.listPolicies(zoneFilter || undefined),
  });

  const [form, setForm] = useState<Partial<AccessPolicy>>({
    priority: 100, allowed_roles: ["user"], require_liveness: false,
  });

  const createMut = useMutation({
    mutationFn: () => accessApi.createPolicy(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policies"] });
      toast.success("Politique créée");
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec"),
  });
  const delMut = useMutation({
    mutationFn: (id: string) => accessApi.deletePolicy(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["policies"] }); toast.success("Supprimée"); },
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 card">
        <div className="mb-3 flex items-center gap-2">
          <select className="input max-w-xs" value={zoneFilter} onChange={e => setZoneFilter(e.target.value)}>
            <option value="">Toutes zones</option>
            {zones.map(z => <option key={z.id} value={z.id}>{z.code}</option>)}
          </select>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Nom</th><th>Priorité</th><th>Rôles</th>
              <th>Jours</th><th>Horaires</th><th>Min sim.</th>
              <th>Liveness</th><th></th>
            </tr>
          </thead>
          <tbody>
            {policies.map(p => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.priority}</td>
                <td className="text-xs">{(p.allowed_roles || []).join(", ")}</td>
                <td className="text-xs text-slate-400">{(p.allowed_days ?? []).join(", ") || "tous"}</td>
                <td className="text-xs text-slate-400">
                  {p.start_time && p.end_time ? `${p.start_time}–${p.end_time}` : "24/7"}
                </td>
                <td>{p.min_similarity != null ? p.min_similarity.toFixed(2) : "—"}</td>
                <td>{p.require_liveness ? <span className="badge-green">oui</span> : "—"}</td>
                <td className="text-right">
                  {isAdmin && (
                    <button className="btn-danger" onClick={() => delMut.mutate(p.id)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {policies.length === 0 && (
              <tr><td colSpan={8} className="text-center py-6 text-slate-500">Aucune politique</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <div className="card">
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <Plus className="h-4 w-4" /> Nouvelle politique
          </h3>
          <form onSubmit={e => { e.preventDefault(); createMut.mutate(); }} className="space-y-3 text-sm">
            <div>
              <label className="label">Zone *</label>
              <select className="input" required value={form.zone_id ?? ""}
                      onChange={e => setForm({ ...form, zone_id: e.target.value })}>
                <option value="">Choisir…</option>
                {zones.map(z => <option key={z.id} value={z.id}>{z.code}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Nom *</label>
              <input className="input" required
                     value={form.name ?? ""}
                     onChange={e => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="label">Priorité (élevée = évaluée en premier)</label>
              <input type="number" className="input" min={0} max={1000}
                     value={form.priority ?? 100}
                     onChange={e => setForm({ ...form, priority: Number(e.target.value) })} />
            </div>
            <div>
              <label className="label">Rôles autorisés</label>
              <div className="flex flex-wrap gap-2">
                {ALL_ROLES.map(r => (
                  <label key={r} className="text-xs flex items-center gap-1 px-2 py-1 border border-slate-700 rounded">
                    <input type="checkbox"
                      checked={form.allowed_roles?.includes(r) ?? false}
                      onChange={e => {
                        const set = new Set(form.allowed_roles ?? []);
                        e.target.checked ? set.add(r) : set.delete(r);
                        setForm({ ...form, allowed_roles: Array.from(set) });
                      }} />
                    {r}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="label">Jours (vide = tous)</label>
              <div className="flex flex-wrap gap-1">
                {ALL_DAYS.map(d => (
                  <label key={d} className="text-xs flex items-center gap-1 px-2 py-1 border border-slate-700 rounded">
                    <input type="checkbox"
                      checked={form.allowed_days?.includes(d) ?? false}
                      onChange={e => {
                        const set = new Set(form.allowed_days ?? []);
                        e.target.checked ? set.add(d) : set.delete(d);
                        setForm({ ...form, allowed_days: Array.from(set) });
                      }} />
                    {d}
                  </label>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">Début (HH:MM)</label>
                <input className="input" placeholder="07:00"
                       value={form.start_time ?? ""}
                       onChange={e => setForm({ ...form, start_time: e.target.value })} />
              </div>
              <div>
                <label className="label">Fin (HH:MM)</label>
                <input className="input" placeholder="20:00"
                       value={form.end_time ?? ""}
                       onChange={e => setForm({ ...form, end_time: e.target.value })} />
              </div>
            </div>
            <div>
              <label className="label">Similarité min. (0–1)</label>
              <input type="number" step={0.05} min={0} max={1} className="input"
                     value={form.min_similarity ?? ""}
                     onChange={e => setForm({ ...form, min_similarity: e.target.value ? Number(e.target.value) : undefined })} />
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.require_liveness ?? false}
                     onChange={e => setForm({ ...form, require_liveness: e.target.checked })} />
              Exiger liveness
            </label>
            <button disabled={createMut.isPending || !form.zone_id || !form.name}
                    className="btn-primary w-full justify-center">
              {createMut.isPending ? "…" : "Créer"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
