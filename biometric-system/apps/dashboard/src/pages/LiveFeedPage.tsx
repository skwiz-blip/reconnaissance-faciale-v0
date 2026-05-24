import { useEffect, useRef, useState } from "react";
import { Camera, Play, Square, Settings2 } from "lucide-react";
import toast from "react-hot-toast";
import { tokenStorage } from "@/api/client";
import type { WsCameraResult } from "@/api/types";

/**
 * Live feed: capture webcam → envoie une frame par intervalle au WS backend.
 * Overlay des bounding boxes (côté approximation : on n'envoie qu'un seul visage,
 * on dessine le badge de matching).
 */
export default function LiveFeedPage() {
  const videoRef  = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef     = useRef<WebSocket | null>(null);
  const intervalRef = useRef<number | null>(null);

  const [cameraId, setCameraId] = useState("default");
  const [fps, setFps]           = useState(3);
  const [checkLiveness, setLiv] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [results, setResults] = useState<WsCameraResult[]>([]);
  const [status, setStatus]   = useState<string>("Inactif");

  function startCamera(): Promise<void> {
    return navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } })
      .then(stream => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          return videoRef.current.play();
        }
      });
  }

  function stopCamera() {
    const stream = videoRef.current?.srcObject as MediaStream | null;
    stream?.getTracks().forEach(t => t.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  function captureFrame(): string | null {
    if (!videoRef.current || !canvasRef.current) return null;
    const v = videoRef.current;
    const c = canvasRef.current;
    c.width  = v.videoWidth;
    c.height = v.videoHeight;
    const ctx = c.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(v, 0, 0);
    return c.toDataURL("image/jpeg", 0.7);
  }

  async function start() {
    try {
      await startCamera();
    } catch (e: any) {
      toast.error(`Caméra: ${e.message}`);
      return;
    }
    const token = tokenStorage.getAccess();
    if (!token) { toast.error("Non authentifié"); return; }

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host  = window.location.host; // Vite proxy → 8000
    const ws = new WebSocket(`${proto}://${host}/ws/camera/${encodeURIComponent(cameraId)}?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => setStatus("Connecté");
    ws.onclose = () => setStatus("Déconnecté");
    ws.onerror = () => setStatus("Erreur WS");
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "result") {
          setResults(prev => [msg, ...prev].slice(0, 30));
        }
      } catch { /* ignore */ }
    };

    intervalRef.current = window.setInterval(() => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const dataUrl = captureFrame();
      if (!dataUrl) return;
      ws.send(JSON.stringify({ type: "frame", data: dataUrl, liveness: checkLiveness }));
    }, Math.max(150, Math.floor(1000 / fps)));

    setStreaming(true);
  }

  function stop() {
    if (intervalRef.current) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    stopCamera();
    setStreaming(false);
    setStatus("Inactif");
  }

  useEffect(() => () => stop(), []);

  const latest = results[0];

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Camera className="h-6 w-6" /> Live feed
          </h1>
          <p className="text-sm text-slate-400">Status: {status}</p>
        </div>
        <div className="flex items-center gap-2">
          {!streaming
            ? <button onClick={start} className="btn-primary"><Play className="h-4 w-4" /> Démarrer</button>
            : <button onClick={stop} className="btn-danger"><Square className="h-4 w-4" /> Arrêter</button>}
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 card">
          <div className="relative aspect-video bg-black rounded-md overflow-hidden">
            <video ref={videoRef} className="h-full w-full object-cover" muted playsInline />
            <canvas ref={canvasRef} className="hidden" />
            {latest && (
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-4">
                <div className="flex items-center gap-3">
                  <span className={
                    latest.event_type === "recognized" ? "badge-green" :
                    latest.event_type === "unknown"    ? "badge-amber" :
                    "badge-red"
                  }>{latest.event_type}</span>
                  {latest.matches[0] && (
                    <span className="text-white">
                      {latest.matches[0].full_name} ·{" "}
                      <span className="text-emerald-300">
                        {(latest.matches[0].similarity * 100).toFixed(1)}%
                      </span>
                    </span>
                  )}
                  <span className="text-xs text-slate-400 ml-auto">
                    {latest.processing_ms.toFixed(0)} ms · liveness {(latest.liveness_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold mb-3 flex items-center gap-2">
              <Settings2 className="h-4 w-4" /> Paramètres
            </h3>
            <div className="space-y-3">
              <div>
                <label className="label">Camera ID</label>
                <input className="input" value={cameraId} onChange={e => setCameraId(e.target.value)} />
              </div>
              <div>
                <label className="label">FPS d'envoi: {fps}</label>
                <input type="range" min={1} max={10} value={fps}
                       onChange={e => setFps(Number(e.target.value))} className="w-full" />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={checkLiveness} onChange={e => setLiv(e.target.checked)} />
                Vérifier liveness
              </label>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-3">Historique frames</h3>
            <div className="space-y-1 max-h-64 overflow-y-auto text-xs">
              {results.map((r, i) => (
                <div key={i} className="flex items-center justify-between text-slate-300">
                  <span>#{r.frame_id}</span>
                  <span className={
                    r.event_type === "recognized" ? "text-emerald-300" :
                    r.event_type === "unknown"    ? "text-amber-300" :
                    "text-red-300"
                  }>{r.event_type}</span>
                  <span className="text-slate-500">{r.processing_ms.toFixed(0)}ms</span>
                </div>
              ))}
              {results.length === 0 && <div className="text-slate-500">—</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
