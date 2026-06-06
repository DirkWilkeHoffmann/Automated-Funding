"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Building2,
  Clock,
  Key,
  LayoutDashboard,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Settings2,
  Users,
  Zap,
} from "lucide-react";
import { useAuth, signOut } from "../lib/auth";
import { api } from "../lib/api";
import { Tooltip } from "./ui/tooltip";

type NavItem = { href: string; label: string; icon: any };

const MAIN_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scrape", label: "Scrape & Analyse", icon: Zap },
  { href: "/results", label: "Results", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

const ADMIN_ITEMS: NavItem[] = [
  { href: "/admin/organisation", label: "Organisation & AI", icon: Building2 },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/keys", label: "API Keys", icon: Key },
  { href: "/admin/pending", label: "Pending URLs", icon: Clock },
  { href: "/discovery", label: "Auto-Discovery", icon: Radar },
];

const STORAGE_KEY = "sidebar_collapsed_v1";

function getInitials(email: string): string {
  const parts = email.split("@")[0].split(/[._-]/);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("");
}

function NavLink({ item, active, collapsed }: { item: NavItem; active: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  const el = (
    <Link
      href={item.href}
      className={`sidebar-link relative ${collapsed ? "justify-center px-0" : ""} ${
        active
          ? "bg-white/10 text-white before:absolute before:inset-y-1 before:left-0 before:w-0.5 before:rounded-full before:bg-brand"
          : "text-slate-400 hover:text-white"
      }`}
    >
      <Icon size={16} className="shrink-0" />
      {!collapsed && <span className="truncate text-[13px]">{item.label}</span>}
    </Link>
  );
  if (collapsed) return <Tooltip label={item.label}>{el}</Tooltip>;
  return el;
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  });
  const [isSuperuser, setIsSuperuser] = useState(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === "1") setCollapsed(true);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    try { window.localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0"); }
    catch { /* ignore */ }
  }, [collapsed]);

  useEffect(() => {
    if (!user) return;
    api.adminUsers().then(() => setIsSuperuser(true)).catch(() => setIsSuperuser(false));
  }, [user]);

  const handleSignOut = async () => {
    await signOut();
    router.replace("/login");
  };

  const isActive = (item: NavItem) =>
    pathname === item.href ||
    (item.href !== "/" && pathname.startsWith(item.href));

  return (
    <aside
      className={`relative flex flex-col overflow-hidden bg-gradient-to-b from-slate-900 via-slate-950 to-slate-900 text-white shadow-xl transition-all duration-200 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      {/* Top ambient glow */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-brand/20 to-transparent blur-3xl opacity-40" />

      {/* Brand header */}
      <div className="flex items-center justify-between px-3 py-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-brand-dark text-xs font-bold shadow-md">
            AF
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold leading-tight">Automated Funding</p>
              <p className="text-[10px] uppercase tracking-widest text-slate-500">Discover · Analyse · Track</p>
            </div>
          )}
        </div>
        <button
          type="button"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-500 transition hover:bg-white/10 hover:text-white focus:outline-none"
          onClick={() => setCollapsed((v) => !v)}
          aria-label="Toggle navigation"
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4 space-y-4">
        {/* Main section */}
        <div>
          {!collapsed && (
            <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-600">Main</p>
          )}
          <div className="space-y-0.5">
            {MAIN_ITEMS.map((item) => (
              <NavLink key={item.href} item={item} active={isActive(item)} collapsed={collapsed} />
            ))}
          </div>
        </div>

        {/* Admin section */}
        {isSuperuser && (
          <div>
            {!collapsed && (
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-600">Admin</p>
            )}
            {collapsed && <div className="my-2 border-t border-white/10" />}
            <div className="space-y-0.5">
              {ADMIN_ITEMS.map((item) => (
                <NavLink key={item.href} item={item} active={isActive(item)} collapsed={collapsed} />
              ))}
            </div>
          </div>
        )}
      </nav>

      {/* Footer */}
      <div className="mx-2 mb-2 space-y-1.5">
        <div className="border-t border-white/10" />

        {/* User chip */}
        {user && !collapsed && (
          <div className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 backdrop-blur">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-dark text-[10px] font-semibold text-white">
              {getInitials(user.email ?? "U")}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[11px] leading-tight text-slate-300">{user.email}</p>
              {isSuperuser && (
                <span className="mt-0.5 inline-block rounded bg-amber-500/20 px-1.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300">
                  Superuser
                </span>
              )}
            </div>
          </div>
        )}

        {/* Sign out */}
        {collapsed ? (
          <Tooltip label="Sign out">
            <button
              type="button"
              onClick={handleSignOut}
              className="sidebar-link w-full justify-center px-0 text-slate-500 hover:bg-red-500/10 hover:text-red-300"
            >
              <LogOut size={16} />
            </button>
          </Tooltip>
        ) : (
          <button
            type="button"
            onClick={handleSignOut}
            className="sidebar-link w-full text-slate-500 hover:bg-red-500/10 hover:text-red-300"
          >
            <LogOut size={16} />
            <span className="text-[13px]">Sign out</span>
          </button>
        )}
      </div>
    </aside>
  );
}
