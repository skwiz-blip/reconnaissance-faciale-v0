import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export default function ProtectedRoute({
  children,
  requireAdmin = false,
}: {
  children: React.ReactNode;
  requireAdmin?: boolean;
}) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-400">
        Chargement…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (requireAdmin && user.role !== "admin") {
    return (
      <div className="card mx-auto mt-12 max-w-md text-center">
        <h2 className="text-lg font-semibold text-red-300">Accès refusé</h2>
        <p className="mt-2 text-sm text-slate-400">Cette page est réservée aux administrateurs.</p>
      </div>
    );
  }
  return <>{children}</>;
}
