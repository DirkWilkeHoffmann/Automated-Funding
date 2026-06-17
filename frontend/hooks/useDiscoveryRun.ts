"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DiscoveryProgress } from "../lib/api";

const POLL_INTERVAL_MS = 2000;
const PERSIST_KEY = "discovery_last_run_id";

export type UseDiscoveryRunState = {
  progress: DiscoveryProgress | null;
  triggering: boolean;
  error: string | null;
  cancelling: boolean;
};

export type UseDiscoveryRun = UseDiscoveryRunState & {
  trigger: () => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
};

export function useDiscoveryRun(): UseDiscoveryRun {
  const [progress, setProgress] = useState<DiscoveryProgress | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runIdRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const poll = useCallback(async (runId: string) => {
    try {
      const snap = await api.discoveryRunProgress(runId);
      setProgress(snap);
      if (!["running", "running_docs"].includes(snap.status)) {
        stopPolling();
      }
    } catch (e: any) {
      const msg = e?.message ?? "";
      if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
        stopPolling();
        return;
      }
      setError(msg || "Failed to fetch run progress");
    }
  }, [stopPolling]);

  // Restore from localStorage on mount so the panel survives page refresh.
  useEffect(() => {
    if (runIdRef.current) return;
    let savedId: string | null = null;
    try { savedId = localStorage.getItem(PERSIST_KEY); } catch { /* SSR guard */ }
    if (!savedId) return;

    runIdRef.current = savedId;
    api.discoveryRunProgress(savedId)
      .then((snap) => {
        setProgress(snap);
        if (["running", "running_docs"].includes(snap.status)) {
          pollRef.current = setInterval(() => poll(savedId!), POLL_INTERVAL_MS);
        }
      })
      .catch(() => {
        try { localStorage.removeItem(PERSIST_KEY); } catch { /* ignore */ }
        runIdRef.current = null;
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const trigger = useCallback(async () => {
    setTriggering(true);
    setError(null);
    setProgress(null);
    try {
      const { id } = await api.triggerDiscoveryRun();
      runIdRef.current = id;
      try { localStorage.setItem(PERSIST_KEY, id); } catch { /* ignore */ }
      await poll(id);
      stopPolling();
      pollRef.current = setInterval(() => poll(id), POLL_INTERVAL_MS);
    } catch (e: any) {
      setError(e?.message || "Failed to start discovery run");
    } finally {
      setTriggering(false);
    }
  }, [poll, stopPolling]);

  const cancel = useCallback(async () => {
    const id = runIdRef.current ?? progress?.run_id;
    if (!id) return;
    setCancelling(true);
    try {
      const snap = await api.cancelDiscoveryRun(id);
      setProgress(snap);
    } catch (e: any) {
      setError(e?.message || "Cancel failed");
    } finally {
      setCancelling(false);
    }
  }, [progress?.run_id]);

  const reset = useCallback(() => {
    stopPolling();
    runIdRef.current = null;
    setProgress(null);
    setError(null);
    try { localStorage.removeItem(PERSIST_KEY); } catch { /* ignore */ }
  }, [stopPolling]);

  return { progress, triggering, cancelling, error, trigger, cancel, reset };
}
