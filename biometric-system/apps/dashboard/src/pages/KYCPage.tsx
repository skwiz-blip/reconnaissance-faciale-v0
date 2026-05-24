import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { kycApi } from "@/api/endpoints";

const DOC_TYPES = ["passport", "id_card", "driver_license", "residence_permit"] as const;

export default function KYCPage() {
  const [docType, setDocType] = useState<typeof DOC_TYPES[number]>("passport");
  const [selfie, setSelfie]   = useState<File | null>(null);
  const [doc, setDoc]         = useState<File | null>(null);
  const [session, setSession] = useState<any>(null);
  const [verdict, setVerdict] = useState<any>(null);

  const startMut = useMutation({
    mutationFn: () => kycApi.start(docType, true),
    onSuccess: (s) => { setSession(s); setVerdict(null); toast.success("Session démarrée"); },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec start"),
  });

  const submitMut = useMutation({
    mutationFn: async () => {
      if (!session || !selfie || !doc) throw new Error("incomplet");
      const [selfieB64, docB64] = await Promise.all([fileToBase64(selfie), fileToBase64(doc)]);
      return kycApi.submit(session.session_token, selfieB64, docB64);
    },
    onSuccess: (v) => {
      setVerdict(v);
      const fn = v.decision === "approved" ? toast.success
              : v.decision === "review"   ? toast
              : toast.error;
      fn(`KYC ${v.decision.toUpperCase()} · confiance ${(v.confidence * 100).toFixed(0)}%`);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Échec submit"),
  });

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">KYC</h1>
        <p className="text-sm text-slate-400">
          Vérification biométrique : selfie ↔ document + OCR + MRZ + fraud detection
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card space-y-3">
          <h3 className="font-semibold">1 · Session</h3>
          <div>
            <label className="label">Type de document</label>
            <select className="input" value={docType}
                    onChange={e => setDocType(e.target.value as any)}>
              {DOC_TYPES.map(d => <option key={d}>{d}</option>)}
            </select>
          </div>
          <button onClick={() => startMut.mutate()} disabled={startMut.isPending}
                  className="btn-primary w-full justify-center">
            {startMut.isPending ? "…" : "Démarrer une session"}
          </button>
          {session && (
            <div className="text-xs text-slate-400 break-all border-t border-slate-800 pt-2">
              <div>session_id: <span className="text-slate-300 font-mono">{session.session_id}</span></div>
              <div>token: <span className="font-mono">{session.session_token.slice(0, 16)}…</span></div>
              {session.challenge && (
                <div className="mt-1">
                  Challenge: <span className="badge-slate">{session.challenge.action}</span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="card space-y-3">
          <h3 className="font-semibold">2 · Soumission</h3>
          <div>
            <label className="label">Selfie</label>
            <input type="file" accept="image/*"
                   onChange={e => setSelfie(e.target.files?.[0] ?? null)}
                   className="block w-full text-sm text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white" />
          </div>
          <div>
            <label className="label">Document</label>
            <input type="file" accept="image/*"
                   onChange={e => setDoc(e.target.files?.[0] ?? null)}
                   className="block w-full text-sm text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white" />
          </div>
          <button onClick={() => submitMut.mutate()}
                  disabled={!session || !selfie || !doc || submitMut.isPending}
                  className="btn-primary w-full justify-center">
            {submitMut.isPending ? "Traitement…" : "Lancer la vérification"}
          </button>
        </div>
      </div>

      {verdict && (
        <div className="card">
          <h3 className="font-semibold mb-3">Verdict</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <Metric label="Décision" value={verdict.decision} tone={
              verdict.decision === "approved" ? "green" :
              verdict.decision === "review"   ? "amber" : "red"
            } />
            <Metric label="Confiance" value={`${(verdict.confidence * 100).toFixed(0)}%`} />
            <Metric label="Face match"
                    value={verdict.face_match_score ? `${(verdict.face_match_score * 100).toFixed(0)}%` : "—"} />
            <Metric label="Risk score"
                    value={verdict.risk_score ? `${(verdict.risk_score * 100).toFixed(0)}%` : "—"}
                    tone={verdict.risk_score > 0.4 ? "red" : "green"} />
          </div>
          {verdict.fraud_flags.length > 0 && (
            <div className="mb-3">
              <div className="text-xs text-slate-400 mb-1">Fraud flags</div>
              <div className="flex flex-wrap gap-1">
                {verdict.fraud_flags.map((f: string) => (
                  <span key={f} className="badge-red">{f}</span>
                ))}
              </div>
            </div>
          )}
          {verdict.mrz && (
            <details className="mb-2">
              <summary className="text-sm cursor-pointer">MRZ</summary>
              <pre className="text-xs bg-slate-800 p-2 rounded mt-1 overflow-auto">
                {JSON.stringify(verdict.mrz, null, 2)}
              </pre>
            </details>
          )}
          <details>
            <summary className="text-sm cursor-pointer">Réponse brute</summary>
            <pre className="text-xs bg-slate-800 p-2 rounded mt-1 overflow-auto">
              {JSON.stringify(verdict, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "green" | "amber" | "red" }) {
  const toneCls = {
    slate: "bg-slate-800 text-slate-100",
    green: "bg-emerald-500/10 text-emerald-300",
    amber: "bg-amber-500/10 text-amber-300",
    red:   "bg-red-500/10 text-red-300",
  }[tone];
  return (
    <div className={`rounded-md p-3 ${toneCls}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="text-lg font-bold">{value}</div>
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
