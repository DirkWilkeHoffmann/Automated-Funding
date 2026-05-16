"use client";

import type { ReactNode } from "react";
import { Fragment } from "react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";

type ResultRecord = Record<string, any>;

/**
 * ResultsTable: Renders results table with sorting, row expansion, and detail views
 */
interface ResultsTableProps {
  results: ResultRecord[];
  selectedRowKey: string | null;
  expandedRows: Set<string>;
  pinnedRowKey: string | null;
  searchQuery: string;
  onRowSelect: (rowKey: string) => void;
  onToggleExpand: (rowKey: string) => void;
  onTogglePin: (rowKey: string) => void;
  detailFields: Array<{
    accessor: string;
    label: string;
    formatter?: (row: ResultRecord) => string;
  }>;
  showEvidence: boolean;
  loading?: boolean;
  error?: string | null;
}

interface TableColumn {
  accessor: string;
  label: string;
  widthClassName: string;
  render?: (row: ResultRecord, searchQuery: string) => ReactNode;
}

const eligibilityTone: Record<string, "accent" | "muted" | "outline"> = {
  "Highly Eligible": "accent",
  Eligible: "accent",
  "Possibly Eligible": "muted",
  "Low Match": "outline",
  "Not Eligible": "outline",
};

function highlightText(value: any, query: string): ReactNode {
  const text = normalizeText(value);
  if (!text) return "-";
  const trimmedQuery = query.trim();
  if (!trimmedQuery) return text;

  const queryLower = trimmedQuery.toLowerCase();
  const regex = new RegExp(`(${escapeRegExp(trimmedQuery)})`, "ig");
  return text.split(regex).map((part, idx) =>
    part.toLowerCase() === queryLower ? (
      <mark key={`${part}-${idx}`} className="rounded bg-amber-200/80 px-0.5 text-inherit">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

function normalizeText(val: any) {
  if (val === null || val === undefined) return "";
  if (Array.isArray(val)) return val.join(" ");
  return String(val);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatValue(val: any) {
  if (val === null || val === undefined || val === "") return "-";
  return Array.isArray(val) ? val.join(", ") : String(val);
}

function getRowKey(row: ResultRecord, idx: number) {
  return (
    row.fund_url || row.fund_name || row.source_folder || row.extraction_timestamp || `row-${idx}`
  );
}

export function ResultsTable({
  results,
  selectedRowKey,
  expandedRows,
  pinnedRowKey,
  searchQuery,
  onRowSelect,
  onToggleExpand,
  onTogglePin,
  detailFields,
  showEvidence,
  loading = false,
  error = null,
}: ResultsTableProps) {
  const tableColumns: TableColumn[] = [
    {
      accessor: "fund_name",
      label: "Fund details",
      widthClassName: "w-[50%]",
      render: (row: ResultRecord) => (
        <div className="space-y-1 min-w-0 min-h-[4.5rem]">
          <div className="flex items-center gap-2 min-w-0">
            <p className="min-w-0 break-words text-sm font-semibold text-neutral-900">
              {highlightText(row.fund_name || "Unnamed fund", searchQuery)}
            </p>
            <Badge
              variant={eligibilityTone[row.eligibility] || "outline"}
              className="shrink-0 whitespace-nowrap"
            >
              {row.eligibility || "Unknown"}
            </Badge>
          </div>
          {row.fund_url ? (
            <a
              href={row.fund_url}
              target="_blank"
              rel="noreferrer"
              className="block min-w-0 truncate text-xs text-neutral-600 underline decoration-neutral-300 underline-offset-4 hover:text-neutral-900"
            >
              {highlightText(row.fund_url, searchQuery)}
            </a>
          ) : (
            <p className="text-xs text-neutral-500">No URL provided.</p>
          )}
          {row.notes && (
            <p className="text-xs text-neutral-600 truncate">
              {highlightText(row.notes, searchQuery)}
            </p>
          )}
        </div>
      ),
    },
    {
      accessor: "applicant_types",
      label: "Audience & scope",
      widthClassName: "w-[30%]",
      render: (row: ResultRecord) => (
        <div className="space-y-1 text-xs text-neutral-600 min-h-[4.5rem]">
          <p className="truncate">
            <span className="font-semibold text-neutral-800">Applicants:</span>{" "}
            {highlightText(formatValue(row.applicant_types), searchQuery)}
          </p>
          <p className="truncate">
            <span className="font-semibold text-neutral-800">Focus:</span>{" "}
            {highlightText(formatValue(row.beneficiary_focus), searchQuery)}
          </p>
          <p className="truncate">
            <span className="font-semibold text-neutral-800">Scope:</span>{" "}
            {highlightText(formatValue(row.geographic_scope), searchQuery)}
          </p>
        </div>
      ),
    },
    {
      accessor: "application_status",
      label: "Status & deadline",
      widthClassName: "w-[20%]",
      render: (row: ResultRecord) => (
        <div className="space-y-1 min-h-[4.5rem]">
          <Badge variant="muted" className="w-fit">
            {highlightText(row.application_status || "Not stated", searchQuery)}
          </Badge>
          <p className="text-xs text-neutral-600 truncate">
            Deadline: {highlightText(row.deadline || "Not listed", searchQuery)}
          </p>
        </div>
      ),
    },
  ];

  if (loading) {
    return <p className="text-sm text-neutral-600">Loading results...</p>;
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>;
  }

  return (
    <Table className="table-fixed">
      <TableHeader>
        <TableRow className="bg-neutral-50">
          <TableHead className="w-12">Details</TableHead>
          {tableColumns.map((col) => (
            <TableHead key={col.accessor} className={col.widthClassName}>
              {col.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((row, idx) => {
          const rowKey = getRowKey(row, idx);
          const isSelected = selectedRowKey === rowKey;
          const isPinned = pinnedRowKey === rowKey;
          const isExpanded = expandedRows.has(rowKey) || isPinned;

          return (
            <Fragment key={`${rowKey}-${idx}`}>
              <TableRow
                className={`${isSelected ? "ring-1 ring-neutral-900/30 ring-inset" : ""} ${
                  isPinned ? "ring-2 ring-orange-400/70 ring-inset" : ""
                }`}
                onClick={() => onRowSelect(rowKey)}
              >
                <TableCell className="w-12">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 border border-neutral-200 bg-white text-xs font-semibold text-neutral-700 hover:border-neutral-900"
                    aria-expanded={isExpanded}
                    title={isExpanded ? "Collapse details" : "Expand details"}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleExpand(rowKey);
                    }}
                  >
                    {isExpanded ? "v" : ">"}
                  </Button>
                </TableCell>
                {tableColumns.map((col) => (
                  <TableCell key={col.accessor} className={col.widthClassName}>
                    {col.render ? col.render(row, searchQuery) : (row[col.accessor] ?? "-")}
                  </TableCell>
                ))}
              </TableRow>
              {isExpanded && (
                <TableRow className="bg-white">
                  <TableCell colSpan={tableColumns.length + 1} className="bg-white">
                    <div className="min-w-0 rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div className="space-y-1">
                          <p className="text-xs uppercase tracking-wide text-neutral-500">Fund</p>
                          <p className="text-base font-semibold text-neutral-900">
                            {highlightText(row.fund_name || "Unnamed fund", searchQuery)}
                          </p>
                          {row.fund_url ? (
                            <a
                              href={row.fund_url}
                              target="_blank"
                              rel="noreferrer"
                              className="block break-all text-xs text-neutral-600 underline decoration-neutral-300 underline-offset-4 hover:text-neutral-900"
                            >
                              {highlightText(row.fund_url, searchQuery)}
                            </a>
                          ) : (
                            <p className="text-xs text-neutral-500">No URL provided.</p>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={eligibilityTone[row.eligibility] || "outline"}>
                            {row.eligibility || "Unknown"}
                          </Badge>
                          {isPinned && <Badge variant="outline">Pinned</Badge>}
                          {isPinned && (
                            <button
                              className="text-xs text-neutral-500 underline"
                              onClick={() => onTogglePin(rowKey)}
                            >
                              Clear pin
                            </button>
                          )}
                        </div>
                      </div>
                      {!showEvidence && (
                        <p className="text-xs text-neutral-500">
                          Evidence hidden. Press E to show it.
                        </p>
                      )}
                      <div className="space-y-2">
                        {detailFields.map((field) => (
                          <div
                            key={field.accessor}
                            className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2"
                          >
                            <p className="text-[11px] uppercase tracking-wide text-neutral-500">
                              {field.label}
                            </p>
                            <p className="mt-1 whitespace-pre-wrap break-words text-sm text-neutral-900">
                              {highlightText(
                                field.formatter
                                  ? field.formatter(row)
                                  : formatValue(row[field.accessor as keyof ResultRecord]),
                                searchQuery
                              )}
                            </p>
                          </div>
                        ))}
                      </div>
                      {row.pdf_text && (
                        <div className="mt-4">
                          <details className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
                            <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-neutral-600">
                              PDF text (truncated)
                            </summary>
                            <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-xs text-neutral-700">
                              {highlightText(String(row.pdf_text), searchQuery)}
                            </pre>
                          </details>
                        </div>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
      {results.length === 0 && <TableCaption>No results match your filters yet.</TableCaption>}
    </Table>
  );
}
