"use client";

import { useEffect, useState, useCallback } from "react";
import { api, PendingUrlItem } from "../../../lib/api";

export default function PendingUrlsPage() {
  const [items, setItems] = useState<PendingUrlItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.adminListPendingUrls();
      setItems(data);
    } catch {
      setActionMsg("Failed to load pending URLs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected(
      selected.size === items.length ? new Set() : new Set(items.map((i) => i.id))
    );

  const approve = async () => {
    if (!selected.size) return;
    setActionMsg("Queuing scrape job…");
    try {
      const res = await api.adminApprovePendingUrls(Array.from(selected));
      setActionMsg(`Scrape job ${res.job_id} started for ${res.url_count} URL(s).`);
      setSelected(new Set());
      load();
    } catch {
      setActionMsg("Approve failed.");
    }
  };

  const reject = async () => {
    if (!selected.size) return;
    setActionMsg("Rejecting…");
    try {
      const res = await api.adminRejectPendingUrls(Array.from(selected));
      setActionMsg(`${res.rejected} URL(s) rejected.`);
      setSelected(new Set());
      load();
    } catch {
      setActionMsg("Reject failed.");
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Pending URLs</h1>
        <span className="text-sm text-slate-500">{items.length} awaiting review</span>
      </div>

      {actionMsg && (
        <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800">
          {actionMsg}
        </div>
      )}

      {loading ? (
        <p className="text-slate-500 text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-slate-500 text-sm">No pending URLs.</p>
      ) : (
        <>
          <div className="mb-3 flex gap-3">
            <button
              onClick={toggleAll}
              className="text-sm text-slate-600 underline underline-offset-2"
            >
              {selected.size === items.length ? "Deselect all" : "Select all"}
            </button>
          </div>

          <div className="rounded border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="w-10 px-3 py-2" />
                  <th className="px-3 py-2 text-left font-medium text-slate-700">URL / Title</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-700">Source</th>
                  <th className="px-3 py-2 text-left font-medium text-slate-700">Added</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={selected.has(item.id) ? "bg-blue-50" : "hover:bg-slate-50"}
                  >
                    <td className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={selected.has(item.id)}
                        onChange={() => toggle(item.id)}
                        className="h-4 w-4 rounded border-slate-300"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline break-all"
                      >
                        {item.url}
                      </a>
                      {item.title && (
                        <div className="text-xs text-slate-500 mt-0.5">{item.title}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-500 text-xs break-all max-w-xs">
                      {item.source_url ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-500 text-xs whitespace-nowrap">
                      {item.created_at ? new Date(item.created_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex gap-3">
            <button
              onClick={reject}
              disabled={!selected.size}
              className="rounded px-4 py-2 text-sm border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              Reject selected ({selected.size})
            </button>
            <button
              onClick={approve}
              disabled={!selected.size}
              className="rounded px-4 py-2 text-sm bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
            >
              Scrape selected ({selected.size})
            </button>
          </div>
        </>
      )}
    </div>
  );
}
