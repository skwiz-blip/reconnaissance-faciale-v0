import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Camera, Users, UserX, GitMerge,
  Shield, FileCheck2, ScrollText, Fingerprint,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import clsx from "clsx";

const ITEMS = [
  { to: "/",           label: "Dashboard",  icon: LayoutDashboard },
  { to: "/live",       label: "Live feed",  icon: Camera },
  { to: "/identities", label: "Identités",  icon: Users },
  { to: "/unknowns",   label: "Inconnus",   icon: UserX },
  { to: "/clusters",   label: "Clusters",   icon: GitMerge },
  { to: "/access",     label: "Accès",      icon: Shield },
  { to: "/kyc",        label: "KYC",        icon: FileCheck2 },
  { to: "/audit",      label: "Audit",      icon: ScrollText, adminOnly: true },
];

export default function Sidebar() {
  const { user } = useAuth();
  return (
    <aside className="hidden md:flex w-64 flex-col border-r border-slate-800 bg-slate-900/70">
      <div className="flex items-center gap-2 px-5 py-5 border-b border-slate-800">
        <Fingerprint className="h-7 w-7 text-brand-500" />
        <div>
          <div className="text-sm font-bold text-slate-100">Biometric</div>
          <div className="text-xs text-slate-400">Console v2.0</div>
        </div>
      </div>
      <nav className="flex-1 px-2 py-4 space-y-1">
        {ITEMS.filter(i => !i.adminOnly || user?.role === "admin").map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) => clsx(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              isActive
                ? "bg-brand-600/15 text-brand-300 ring-1 ring-brand-500/30"
                : "text-slate-300 hover:bg-slate-800/60 hover:text-slate-100"
            )}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 text-[11px] text-slate-500 border-t border-slate-800">
        Phase 4 · Dashboard temps réel
      </div>
    </aside>
  );
}
