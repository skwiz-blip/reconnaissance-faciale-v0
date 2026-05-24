import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Merge } from "lucide-react";
import toast from "react-hot-toast";
import { formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";
import { clustersApi, identitiesApi } from "@/api/endpoints";
import { useAuth } from "@/auth/AuthContext";

export default function ClustersPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return <div className="card text-slate-400">Cette page est réservée aux admins.</div>;
  }

  const { data: clusters = [], isLoading } = useQuery({
    queryKey: ["clusters"], queryFn: clustersApi.list,
  });
  const { data: identitiesData } = useQuery({
    queryKey: ["identities"], queryFn: () => identitiesApi.list(200),
  });

  const runMut = useMutation({
    mutationFn: () => clustersApi.run(0.65, 2),
    onSuccess: (res) => {
      toast.success(`Clustering: ${res.n_clusters} clusters, ${res.n_processed} traités`);
      qc.invalidateQueries({ queryKey: ["clusters"] });
      qc.invalidateQueries({ queryKey: ["unknowns"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec"),
  });

  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Clusters d'inconnus</h1>
          <p className="text-sm text-slate-400">DBSCAN sur les embeddings non résolus</p>
        </div>
        <button onClick={() => runMut.mutate()} disabled={runMut.isPending} className="btn-primary">
          <Play className="h-4 w-4" /> {runMut.isPending ? "En cours…" : "Relancer le clustering"}
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 card">
          {isLoading ? (
            <div className="py-8 text-center text-slate-400">Chargement…</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Cluster</th><th>Taille</th><th>Apparitions</th>
                  <th>Première</th><th>Dernière</th><th></th>
                </tr>
              </thead>
              <tbody>
                {clusters.map(c => (
                  <tr key={c.cluster_id}
                      className={selected === c.cluster_id ? "!bg-brand-600/10" : ""}>
                    <td className="font-mono text-xs">{c.cluster_id}</td>
                    <td>{c.cluster_size}</td>
                    <td>{c.total_appearances}</td>
                    <td className="text-xs text-slate-400">
                      {formatDistanceToNow(new Date(c.first_seen_at), { addSuffix: true, locale: fr })}
                    </td>
                    <td className="text-xs text-slate-400">
                      {formatDistanceToNow(new Date(c.last_seen_at), { addSuffix: true, locale: fr })}
                    </td>
                    <td className="text-right">
                      <button className="btn-secondary"
                              onClick={() => setSelected(c.cluster_id)}>Inspecter</button>
                    </td>
                  </tr>
                ))}
                {clusters.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-6 text-slate-500">
                    Aucun cluster. Relancez le clustering.
                  </td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        <ClusterDetail
          clusterId={selected}
          identities={identitiesData?.items ?? []}
          onMerged={() => {
            qc.invalidateQueries({ queryKey: ["clusters"] });
            qc.invalidateQueries({ queryKey: ["unknowns"] });
            setSelected(null);
          }}
        />
      </div>
    </div>
  );
}

function ClusterDetail({
  clusterId, identities, onMerged,
}: {
  clusterId: string | null;
  identities: any[];
  onMerged: () => void;
}) {
  if (!clusterId) {
    return <div className="card text-slate-500 text-sm">Sélectionnez un cluster pour voir les détails.</div>;
  }
  const { data: faces = [] } = useQuery({
    queryKey: ["cluster-faces", clusterId],
    queryFn:  () => clustersApi.faces(clusterId),
  });
  const [identityId, setIdentityId] = useState(identities[0]?.id ?? "");
  const mergeMut = useMutation({
    mutationFn: () => clustersApi.merge(clusterId, identityId),
    onSuccess: (res) => {
      toast.success(`Fusion: ${res.transferred}/${res.total} transférés`);
      onMerged();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec fusion"),
  });

  return (
    <div className="card space-y-3">
      <h3 className="font-semibold">{clusterId}</h3>
      <div className="text-xs text-slate-400">{faces.length} visages</div>

      <div className="max-h-40 overflow-y-auto space-y-1">
        {faces.map((f: any) => (
          <div key={f.id} className="text-xs flex justify-between text-slate-300">
            <span className="font-mono">{f.temp_id}</span>
            <span>{f.appearances}×</span>
          </div>
        ))}
      </div>

      <div className="border-t border-slate-800 pt-3">
        <label className="label">Fusionner vers une identité</label>
        <select className="input" value={identityId} onChange={e => setIdentityId(e.target.value)}>
          {identities.map((i: any) => (
            <option key={i.id} value={i.id}>{i.full_name}</option>
          ))}
        </select>
        <button
          onClick={() => mergeMut.mutate()}
          disabled={mergeMut.isPending || !identityId}
          className="btn-primary w-full mt-3 justify-center"
        >
          <Merge className="h-4 w-4" />
          {mergeMut.isPending ? "Fusion…" : "Fusionner"}
        </button>
      </div>
    </div>
  );
}
