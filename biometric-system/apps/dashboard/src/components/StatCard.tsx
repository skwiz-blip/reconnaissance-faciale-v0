import { LucideIcon } from "lucide-react";
import clsx from "clsx";

export default function StatCard({
  label, value, icon: Icon, accent = "brand", hint,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  accent?: "brand" | "emerald" | "amber" | "rose";
  hint?: string;
}) {
  const accents = {
    brand:   "text-brand-300 bg-brand-500/10 ring-brand-500/30",
    emerald: "text-emerald-300 bg-emerald-500/10 ring-emerald-500/30",
    amber:   "text-amber-300 bg-amber-500/10 ring-amber-500/30",
    rose:    "text-rose-300 bg-rose-500/10 ring-rose-500/30",
  } as const;
  return (
    <div className="card flex items-center gap-4">
      <div className={clsx("rounded-lg p-3 ring-1", accents[accent])}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
        <div className="text-2xl font-bold text-slate-100 truncate">{value}</div>
        {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
      </div>
    </div>
  );
}
