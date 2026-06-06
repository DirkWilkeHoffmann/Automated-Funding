"use client";

import { useState } from "react";
import { ExternalLink, List, Play, X } from "lucide-react";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

export type ListingItem = { url: string; title: string };

type Props = {
  sourceUrl: string;
  items: ListingItem[];
  onConfirm: (selectedUrls: string[]) => void;
  onDismiss: () => void;
};

export function ListingExpandPanel({ sourceUrl, items, onConfirm, onDismiss }: Props) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(items.map((i) => i.url)));

  const toggle = (url: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(url) ? next.delete(url) : next.add(url);
      return next;
    });

  const allSelected = selected.size === items.length;
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.url)));

  const handleConfirm = () => {
    const chosen = items.map((i) => i.url).filter((u) => selected.has(u));
    if (chosen.length > 0) onConfirm(chosen);
  };

  return (
    <div className="card-base overflow-hidden">
      <div className="h-0.5 bg-gradient-to-r from-amber-400 via-orange-400 to-transparent" />
      <div className="px-5 py-4 space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <List size={15} className="shrink-0 text-amber-500" />
            <div>
              <p className="font-semibold text-slate-900">
                Listing page detected — {items.length} grant{items.length !== 1 ? "s" : ""} found
              </p>
              <p className="text-xs text-slate-500 mt-0.5 truncate max-w-sm">{sourceUrl}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onDismiss}
            className="shrink-0 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X size={14} />
          </button>
        </div>

        <p className="text-xs text-slate-500">
          This URL links to multiple individual grants. Select the ones you want to scrape — each
          will be evaluated separately.
        </p>

        {/* Select-all toggle */}
        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
          <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-700">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
            />
            {allSelected ? "Deselect all" : "Select all"}
          </label>
          <span className="text-xs text-slate-400">{selected.size} selected</span>
        </div>

        {/* URL list */}
        <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
          {items.map((item) => {
            const isChecked = selected.has(item.url);
            let hostname = item.url;
            try { hostname = new URL(item.url).hostname; } catch { /* keep full url */ }
            return (
              <li
                key={item.url}
                className={cn(
                  "flex items-start gap-2.5 rounded-lg border px-3 py-2 transition cursor-pointer",
                  isChecked
                    ? "border-brand/20 bg-brand-50/30"
                    : "border-slate-100 bg-slate-50 opacity-60"
                )}
                onClick={() => toggle(item.url)}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggle(item.url)}
                  onClick={(e) => e.stopPropagation()}
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-slate-300 accent-brand"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-800">{item.title}</p>
                  <p className="flex items-center gap-1 truncate text-xs text-slate-400">
                    <ExternalLink size={10} />
                    {hostname}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>

        {/* Actions */}
        <div className="flex items-center justify-between gap-3 pt-1">
          <Button variant="ghost" size="sm" onClick={onDismiss} className="text-slate-500">
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={selected.size === 0}
            className="gap-2 bg-brand text-white hover:bg-brand-dark"
          >
            <Play size={13} />
            Add {selected.size} to queue
          </Button>
        </div>
      </div>
    </div>
  );
}
