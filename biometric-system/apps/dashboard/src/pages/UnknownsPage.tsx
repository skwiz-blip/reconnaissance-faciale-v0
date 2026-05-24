import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";
import { unknownsApi, identitiesApi } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";
import type { Identity, UnknownFace } from "@/api/types";

export default function UnknownsPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const { data: unknowns = [], isLoading } = useQuery({
    queryKey: ["unknowns"],
    queryFn:  () => unknownsApi.list(100),
  });
  const { data: identities } = useQuery({
    queryKey: ["identities"],
    queryFn:  () => identitiesApi.list(200),
  });

  const [resolving, setResolving] = useState<UnknownFace | null>(null);

  const resolveMut = useMutation({
    mutationFn: ({ id, identityId, newIdentity }: {
      id: string; identityId?: string; newIdentity?: Partial<Identity>;
    }) => unknownsApi.resolve(id, identityId, newIdentity),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["unknowns"] });
      qc.invalidateQueries({ queryKey: ["identities"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success("Inconnu résolu");
      setResolving(null);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec"),
  });

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Visages inconnus</h1>
        <p className="text-sm text-slate-400">
          {unknowns.length} en attente · résolvez en associant à une identité existante ou créez-en une nouvelle.
        </p>
      </header>

      <div className="card">
        {isLoading ? (
          <div className="py-8 text-center text-slate-400">Chargement…</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Temp ID</th><th>Apparitions</th><th>Première vue</th>
                <th>Dernière vue</th><th>Localisation</th><th>Cluster</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {unknowns.map(u => (
                <tr key={u.id}>
                  <td className="font-mono text-xs">{u.temp_id}</td>
                  <td>{u.appearances}</td>
                  <td className="text-xs text-slate-400">
                    {formatDistanceToNow(new Date(u.first_seen_at), { addSuffix: true, locale: fr })}
                  </td>
                  <td className="text-xs text-slate-400">
                    {formatDistanceToNow(new Date(u.last_seen_at), { addSuffix: true, locale: fr })}
                  </td>
                  <td className="text-slate-400">{u.location ?? "—"}</td>
                  <td>{u.cluster_id ? <span className="badge-slate">{u.cluster_id}</span> : "—"}</td>
                  <td className="text-right">
                    {isAdmin && (
                      <button className="btn-primary" onClick={() => setResolving(u)}>Résoudre</button>
                    )}
                  </td>
                </tr>
              ))}
              {unknowns.length === 0 && (
                <tr><td colSpan={7} className="text-center py-6 text-slate-500">Aucun inconnu pendant</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {resolving && (
        <ResolveModal
          unknown={resolving}
          identities={identities?.items ?? []}
          onClose={() => setResolving(null)}
          onSubmit={(p) => resolveMut.mutate({ id: resolving.id, ...p })}
          busy={resolveMut.isPending}
        />
      )}
    </div>
  );
}

function ResolveModal({
  unknown, identities, onClose, onSubmit, busy,
}: {
  unknown: UnknownFace;
  identities: Identity[];
  onClose: () => void;
  onSubmit: (p: { identityId?: string; newIdentity?: Partial<Identity> }) => void;
  busy: boolean;
}) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [identityId, setIdentityId] = useState<string>(identities[0]?.id ?? "");
  const [newIdentity, setNewIdentity] = useState<Partial<Identity>>({ role: "user" });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="card w-full max-w-md" onClick={e => e.stopPropagation()}>
        <h3 className="font-semibold mb-3">Résoudre {unknown.temp_id}</h3>

        <div className="flex gap-2 mb-4">
          <button className={mode === "existing" ? "btn-primary" : "btn-secondary"}
                  onClick={() => setMode("existing")}>Existante</button>
          <button className={mode === "new" ? "btn-primary" : "btn-secondary"}
                  onClick={() => setMode("new")}>Nouvelle</button>
        </div>

        {mode === "existing" ? (
          <select className="input" value={identityId} onChange={e => setIdentityId(e.target.value)}>
            {identities.map(i => (
              <option key={i.id} value={i.id}>{i.full_name} ({i.role})</option>
            ))}
          </select>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="label">Nom complet *</label>
              <input className="input" required minLength={2}
                onChange={e => setNewIdentity({ ...newIdentity, full_name: e.target.value })} />
            </div>
            <div>
              <label className="label">Email</label>
              <input type="email" className="input"
                onChange={e => setNewIdentity({ ...newIdentity, email: e.target.value })} />
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary">Annuler</button>
          <button
            disabled={busy || (mode === "existing" ? !identityId : !newIdentity.full_name)}
            onClick={() => onSubmit(mode === "existing"
              ? { identityId }
              : { newIdentity })}
            className="btn-primary"
          >{busy ? "…" : "Résoudre"}</button>
        </div>
      </div>
    </div>
  );
}
