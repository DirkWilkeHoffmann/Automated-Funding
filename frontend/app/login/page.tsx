"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Zap } from "lucide-react";
import { signIn } from "../../lib/auth";
import { Button } from "../../components/ui/button";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { error } = await signIn(email, password);
      if (error) throw error;
      router.replace("/");
    } catch (err: any) {
      setError(err.message || "Sign in failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 px-4">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-1/3 h-64 w-64 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute left-1/2 top-2/3 h-48 w-48 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/10 blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm">
        <div className="rounded-2xl border border-white/10 bg-slate-800/60 p-8 shadow-2xl backdrop-blur-sm ring-1 ring-white/5">
          {/* Logo */}
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-brand-dark shadow-lg">
              <Zap size={20} className="text-white" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Automated Funding</p>
              <p className="text-xs text-slate-400">Discover · Analyze · Track</p>
            </div>
          </div>

          <h1 className="mb-6 text-xl font-semibold text-white">Sign in to your account</h1>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-medium text-slate-300">
                Email address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                placeholder="you@example.com"
                className="w-full rounded-lg border border-white/10 bg-slate-700/60 px-3 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-brand/60 focus:outline-none focus:ring-2 focus:ring-brand/20"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="text-xs font-medium text-slate-300">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                  className="w-full rounded-lg border border-white/10 bg-slate-700/60 px-3 py-2.5 pr-10 text-sm text-white placeholder:text-slate-500 focus:border-brand/60 focus:outline-none focus:ring-2 focus:ring-brand/20"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            {error && (
              <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-dark focus:ring-brand/40"
              disabled={loading}
            >
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
