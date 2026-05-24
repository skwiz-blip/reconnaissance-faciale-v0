import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { accessApi } from "@/api/endpoints";

export default function AccessCheckTab() {
  const { data: zones = [] } = useQuery({ queryKey: ["zones"], queryFn: accessApi.listZones });
  const [zoneCode, setZoneCode] = useState("");
  const [accessPoint, setAccessPoint] = useState("door_test");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const base64 = await fileToBase64(file);
      const res = await accessApi.check({
        image_base64: base64,
        zone_code: zoneCode,
        access_point: accessPoint,
        check_liveness: true,
      });
      setResult(res);
      const tone = res.decision === "granted" ? toast.success
                 : res.decision === "alert"   ? toast
                 : toast.error;
      tone(`${res.decision.toUpperCase()} · ${res.reason}`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Échec");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <form onSubmit={onSubmit} className="card space-y-3">
        <h3 className="font-semibold">Tester un accès</h3>
        <div>
          <label className="label">Zone</label>
          <select className="input" required value={zoneCode}
                  onChange={e => setZoneCode(e.target.value)}>
            <option value="">Choisir…</option>
            {zones.map(z => <option key={z.id} value={z.code}>{z.code} ({z.name})</option>)}
          </select>
        </div>
        <div>
          <label className="label">Access point</label>
          <input className="input" required
                 value={accessPoint} onChange={e => setAccessPoint(e.target.value)} />
        </div>
        <div>
          <label className="label">Image (visage)</label>
          <input type="file" accept="image/*" required
                 onChange={e => setFile(e.target.files?.[0] ?? null)}
                 className="block w-full text-sm text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white" />
        </div>
        <button disabled={busy || !file || !zoneCode} className="btn-primary w-full justify-center">
          {busy ? "…" : "Vérifier l'accès"}
        </button>
      </form>

      <div className="card">
        <h3 className="font-semibold mb-3">Résultat</h3>
        {!result && <div className="text-slate-500 text-sm">Pas encore de test.</div>}
        {result && (
          <div className="space-y-2 text-sm">
            <div>Décision: <span className={
              result.decision === "granted" ? "badge-green" :
              result.decision === "alert"   ? "badge-amber" : "badge-red"
            }>{result.decision}</span></div>
            <div>Raison: <span className="text-slate-300">{result.reason}</span></div>
            {result.identity_name && <div>Identité: {result.identity_name}</div>}
            {result.similarity != null && <div>Similarité: {(result.similarity * 100).toFixed(1)}%</div>}
            <div>Liveness: {(result.liveness_score * 100).toFixed(0)}%</div>
            <div>Latence: {result.processing_ms?.toFixed?.(0)} ms</div>
            <pre className="text-xs bg-slate-800 p-2 rounded overflow-auto mt-2">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
