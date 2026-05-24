import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { accessApi } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";
import type { Zone } from "@/api/types";

const LEVELS = ["public", "restricted", "secured", "classified"] as const;

export default function AccessZonesTab() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const { data: zones = [] } = useQuery({
    queryKey: ["zones"], queryFn: accessApi.listZones,
  });

  const [form, setForm] = useState<Partial<Zone>>({ security_level: "public" });

  const createMut = useMutation({
    mutationFn: () => accessApi.createZone(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["zones"] });
      toast.success("Zone créée");
      setForm({ security_level: "public" });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec"),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => accessApi.deleteZone(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["zones"] }); toast.success("Supprimée"); },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec"),
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 card">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th><th>Nom</th><th>Niveau</th><th>Statut</th><th></th>
            </tr>
          </thead>
          <tbody>
            {zones.map(z => (
              <tr key={z.id}>
                <td className="font-mono text-xs">{z.code}</td>
                <td>{z.name}</td>
                <td><span className="badge-slate">{z.security_level}</span></td>
                <td>
                  <span className={z.is_active ? "badge-green" : "badge-red"}>
                    {z.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="text-right">
                  {isAdmin && (
                    <button className="btn-danger"
                            onClick={() => confirm(`Supprimer ${z.code} ?`) && delMut.mutate(z.id)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {zones.length === 0 && (
              <tr><td colSpan={5} className="text-center py-6 text-slate-500">Aucune zone</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {isAdmin && (
        <div className="card">
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            <Plus className="h-4 w-4" /> Nouvelle zone
          </h3>
          <form onSubmit={e => { e.preventDefault(); createMut.mutate(); }} className="space-y-3">
            <div>
              <label className="label">Code *</label>
              <input className="input" required pattern="^[a-z0-9_\-]+$"
                value={form.code ?? ""}
                onChange={e => setForm({ ...form, code: e.target.value })} />
            </div>
            <div>
              <label className="label">Nom *</label>
              <input className="input" required
                value={form.name ?? ""}
                onChange={e => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="label">Niveau</label>
              <select className="input" value={form.security_level}
                onChange={e => setForm({ ...form, security_level: e.target.value as any })}>
                {LEVELS.map(l => <option key={l}>{l}</option>)}
              </select>
            </div>
            <button disabled={createMut.isPending} className="btn-primary w-full justify-center">
              {createMut.isPending ? "…" : "Créer"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
