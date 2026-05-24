import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import LiveFeedPage from "@/pages/LiveFeedPage";
import IdentitiesPage from "@/pages/IdentitiesPage";
import UnknownsPage from "@/pages/UnknownsPage";
import ClustersPage from "@/pages/ClustersPage";
import AccessPage from "@/pages/AccessPage";
import KYCPage from "@/pages/KYCPage";
import AuditPage from "@/pages/AuditPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="/live"        element={<LiveFeedPage />} />
        <Route path="/identities"  element={<IdentitiesPage />} />
        <Route path="/unknowns"    element={<UnknownsPage />} />
        <Route path="/clusters"    element={<ClustersPage />} />
        <Route path="/access/*"    element={<AccessPage />} />
        <Route path="/kyc"         element={<KYCPage />} />
        <Route path="/audit"       element={<ProtectedRoute requireAdmin><AuditPage /></ProtectedRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
