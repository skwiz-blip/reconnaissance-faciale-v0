import { NavLink, Outlet, Route, Routes, Navigate } from "react-router-dom";
import AccessLogsTab from "./access/AccessLogsTab";
import AccessZonesTab from "./access/AccessZonesTab";
import AccessPoliciesTab from "./access/AccessPoliciesTab";
import AccessCheckTab from "./access/AccessCheckTab";
import clsx from "clsx";

const TABS = [
  { to: "logs",     label: "Logs" },
  { to: "zones",    label: "Zones" },
  { to: "policies", label: "Politiques" },
  { to: "check",    label: "Test d'accès" },
];

export default function AccessPage() {
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Contrôle d'accès</h1>
        <p className="text-sm text-slate-400">Zones, politiques RBAC et historique</p>
      </header>

      <nav className="flex gap-1 border-b border-slate-800">
        {TABS.map(t => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) => clsx(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              isActive
                ? "border-brand-500 text-brand-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            )}
          >{t.label}</NavLink>
        ))}
      </nav>

      <Routes>
        <Route index element={<Navigate to="logs" replace />} />
        <Route path="logs"     element={<AccessLogsTab />} />
        <Route path="zones"    element={<AccessZonesTab />} />
        <Route path="policies" element={<AccessPoliciesTab />} />
        <Route path="check"    element={<AccessCheckTab />} />
      </Routes>
    </div>
  );
}
