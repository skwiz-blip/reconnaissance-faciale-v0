import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Upload, X } from "lucide-react";
import toast from "react-hot-toast";
import { identitiesApi } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";
import type { Identity } from "@/api/types";

export default function IdentitiesPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const { data, isLoading } = useQuery({
    queryKey: ["identities"],
    queryFn:  () => identitiesApi.list(100),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [enrollFor,  setEnrollFor]  = useState<Identity | null>(null);

  const createMut = useMutation({
    mutationFn: identitiesApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["identities"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success("Identité créée");
      setShowCreate(false);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec création"),
  });

  const deleteMut = useMutation({
    mutationFn: identitiesApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["identities"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      toast.success("Identité supprimée");
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec suppression"),
  });

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Identités</h1>
        {isAdmin && (
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <Plus className="h-4 w-4" /> Nouvelle identité
          </button>
        )}
      </header>

      <div className="card">
        {isLoading ? (
          <div className="py-8 text-center text-slate-400">Chargement…</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Nom</th><th>Email</th><th>Rôle</th><th>Statut</th>
                <th>Département</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((i: Identity) => (
                <tr key={i.id}>
                  <td className="font-medium">{i.full_name}</td>
                  <td className="text-slate-400">{i.email ?? "—"}</td>
                  <td><span className="badge-slate">{i.role}</span></td>
                  <td>
                    <span className={i.status === "active" ? "badge-green" : "badge-red"}>
                      {i.status}
                    </span>
                  </td>
                  <td className="text-slate-400">{i.department ?? "—"}</td>
                  <td className="text-right space-x-2">
                    <button className="btn-secondary" onClick={() => setEnrollFor(i)}>
                      <Upload className="h-4 w-4" /> Enrôler
                    </button>
                    {isAdmin && (
                      <button
                        className="btn-danger"
                        onClick={() => {
                          if (confirm(`Supprimer ${i.full_name} ?`)) deleteMut.mutate(i.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(data?.items ?? []).length === 0 && (
                <tr><td colSpan={6} className="text-center py-6 text-slate-500">Aucune identité</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMut.mutate(payload)}
          submitting={createMut.isPending}
        />
      )}
      {enrollFor && (
        <EnrollModal identity={enrollFor} onClose={() => setEnrollFor(null)} />
      )}
    </div>
  );
}

function CreateModal({
  onClose, onSubmit, submitting,
}: {
  onClose: () => void;
  onSubmit: (p: Partial<Identity>) => void;
  submitting: boolean;
}) {
  const [form, setForm] = useState<Partial<Identity>>({ role: "user" });
  return (
    <ModalShell title="Nouvelle identité" onClose={onClose}>
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}
        className="space-y-3"
      >
        <div>
          <label className="label">Nom complet *</label>
          <input className="input" required minLength={2}
            onChange={e => setForm({ ...form, full_name: e.target.value })} />
        </div>
        <div>
          <label className="label">Email</label>
          <input type="email" className="input"
            onChange={e => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Rôle</label>
            <select className="input" value={form.role}
              onChange={e => setForm({ ...form, role: e.target.value as Identity["role"] })}>
              <option value="user">user</option>
              <option value="vip">vip</option>
              <option value="admin">admin</option>
              <option value="blocked">blocked</option>
            </select>
          </div>
          <div>
            <label className="label">Département</label>
            <input className="input"
              onChange={e => setForm({ ...form, department: e.target.value })} />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">Annuler</button>
          <button disabled={submitting} className="btn-primary">
            {submitting ? "…" : "Créer"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function EnrollModal({ identity, onClose }: { identity: Identity; onClose: () => void }) {
  const [file, setFile]       = useState<File | null>(null);
  const [busy, setBusy]       = useState(false);
  const [result, setResult]   = useState<any>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const res = await identitiesApi.enroll(identity.id, file);
      setResult(res);
      if (res.success) toast.success(`Embedding ajouté (qualité ${res.quality_score?.toFixed?.(2)})`);
      else toast.error(res.error ?? "Échec");
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Échec");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell title={`Enrôler · ${identity.full_name}`} onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-3">
        <input
          type="file" accept="image/*"
          onChange={e => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white"
        />
        {result && (
          <pre className="text-xs bg-slate-800 p-2 rounded overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">Fermer</button>
          <button disabled={!file || busy} className="btn-primary">
            {busy ? "…" : "Envoyer"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function ModalShell({
  title, onClose, children,
}: {
  title: string; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="card w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
