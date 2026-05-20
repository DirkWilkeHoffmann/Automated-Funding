"use client";

import { useEffect, useState } from "react";
import { AlertCircle, UserPlus, Users } from "lucide-react";
import { api } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

type UserRecord = { id: string; email: string | null; role: string; created_at: string | null };

const inp = "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";

function Section({ icon: Icon, title, desc, children }: { icon: any; title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="card-base overflow-hidden">
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/10 text-brand"><Icon size={15} /></div>
        <div>
          <p className="text-sm font-semibold text-slate-800">{title}</p>
          <p className="text-xs text-slate-500">{desc}</p>
        </div>
      </div>
      <div className="space-y-4 p-5">{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      {children}
    </div>
  );
}

function StatusMsg({ msg }: { msg: string | null }) {
  if (!msg) return null;
  const isErr = msg.startsWith("Error");
  return <p className={`text-xs ${isErr ? "text-red-600" : "text-emerald-600"}`}>{msg}</p>;
}

export default function UsersPage() {
  const [loadError, setLoadError] = useState<string | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<"user" | "superuser">("user");
  const [creating, setCreating] = useState(false);
  const [createStatus, setCreateStatus] = useState<string | null>(null);

  useEffect(() => {
    api.adminUsers()
      .then((u: UserRecord[]) => setUsers(u))
      .catch((e: any) => setLoadError(e.message || "Failed to load users"));
  }, []);

  const setRole = async (userId: string, role: "user" | "superuser") => {
    try {
      await api.adminSetUserRole(userId, role);
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role } : u)));
    } catch (e: any) { alert(`Failed: ${e.message}`); }
  };

  const createUser = async () => {
    if (!newEmail.trim() || !newPassword.trim()) return;
    setCreating(true); setCreateStatus(null);
    try {
      await api.adminCreateUser(newEmail.trim(), newPassword.trim(), newRole);
      setCreateStatus(`User ${newEmail.trim()} created.`);
      setNewEmail(""); setNewPassword("");
      setUsers(await api.adminUsers());
    } catch (e: any) { setCreateStatus(`Error: ${e.message}`); }
    finally { setCreating(false); }
  };

  if (loadError) return (
    <div className="page-content">
      <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <AlertCircle size={14} />{loadError}
      </div>
    </div>
  );

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Admin · Users</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">User Management</h1>
        <p className="mt-1 text-sm text-slate-500">Create accounts and manage access roles.</p>
      </header>

      <Section icon={UserPlus} title="Create User" desc="Add a new account. They can log in immediately.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Row label="Email"><input type="email" className={inp} placeholder="user@example.com" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} autoComplete="off" /></Row>
          <Row label="Password"><input type="password" className={inp} placeholder="Min 6 characters" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" /></Row>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-600">Role</span>
          {(["user", "superuser"] as const).map((r) => (
            <button key={r} type="button" onClick={() => setNewRole(r)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition ${newRole === r ? "bg-brand text-white" : "border border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
              {r}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={createUser} disabled={creating || !newEmail.trim() || !newPassword.trim()}>{creating ? "Creating…" : "Create user"}</Button>
          <StatusMsg msg={createStatus} />
        </div>
      </Section>

      <Section icon={Users} title="All Users" desc="Manage roles. Superusers can access the admin panel.">
        {users.length === 0 ? (
          <p className="text-sm text-slate-500">No users found.</p>
        ) : (
          <div className="divide-y divide-slate-100 -mx-5">
            {users.map((u) => (
              <div key={u.id} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{u.email || u.id.slice(0, 8)}</p>
                  <p className="text-xs text-slate-400">{u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${u.role === "superuser" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>{u.role}</span>
                  <Button variant="outline" size="sm" onClick={() => setRole(u.id, u.role === "user" ? "superuser" : "user")}>
                    {u.role === "user" ? "Promote" : "Demote"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
