"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";
import Sidebar from "./Sidebar";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isLoginRoute = pathname === "/login";

  useEffect(() => {
    if (loading) return;
    if (!user && !isLoginRoute) {
      router.replace("/login");
    }
    if (user && isLoginRoute) {
      router.replace("/");
    }
  }, [user, loading, router, isLoginRoute]);

  if (isLoginRoute) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <div className="flex h-12 w-12 animate-pulse items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-brand-dark text-lg font-bold text-white shadow-card-lg">
            AF
          </div>
          <div className="space-y-2 text-center">
            <div className="h-2 w-24 animate-pulse rounded-full bg-slate-200" />
            <div className="h-2 w-16 animate-pulse rounded-full bg-slate-100" />
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-slate-50">{children}</main>
    </div>
  );
}
