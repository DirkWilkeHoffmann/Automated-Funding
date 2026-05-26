import { getAccessToken } from "./auth";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "https://automated-funding-api--0000001.ambitioussand-ae029d29.eastus.azurecontainerapps.io";

function ngrokHeaders(url: string): Record<string, string> {
  return url.includes("ngrok") ? { "ngrok-skip-browser-warning": "true" } : {};
}

type RequestOptions = RequestInit & {
  headers?: Record<string, string>;
  timeoutMs?: number;
};

async function request<T = any>(path: string, opts?: RequestOptions): Promise<T> {
  const { headers, timeoutMs = 30000, ...rest } = opts || {};
  const token = await getAccessToken();
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};
  const baseUrl = API_BASE_URL;
  const res = await fetch(`${baseUrl}${path}`, {
    ...rest,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      "Content-Type": "application/json",
      ...ngrokHeaders(baseUrl),
      ...authHeaders,
      ...(headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  results: (opts?: { forceRefresh?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.forceRefresh) params.set("force_refresh", "true");
    const query = params.toString();
    return request<{ results: any[] }>(`/results/${query ? `?${query}` : ""}`);
  },
  staleResults: (months = 3, opts?: { forceRefresh?: boolean }) => {
    const params = new URLSearchParams({ months: String(months) });
    if (opts?.forceRefresh) params.set("force_refresh", "true");
    return request<{ results: any[]; months: number; cutoff_timestamp?: string }>(
      `/results/stale?${params}`
    );
  },
  scrapeSingle: (fundUrl: string, fundName?: string) =>
    request("/scrape/single", {
      method: "POST",
      body: JSON.stringify({ fund_url: fundUrl, fund_name: fundName }),
    }),
  scrapeBatch: (
    fundUrls: string[],
    rescrapeUrls?: string[],
    opts?: { rescrapeScope?: "stale" | "any" }
  ) =>
    request("/scrape/batch", {
      method: "POST",
      timeoutMs: 120000,
      body: JSON.stringify({
        fund_urls: fundUrls,
        rescrape_urls: rescrapeUrls || [],
        rescrape_scope: opts?.rescrapeScope || "stale",
      }),
    }),
  jobStatus: (jobId: string) => request(`/scrape/jobs/${jobId}`),
  cancelJob: (jobId: string) =>
    request(`/scrape/jobs/${jobId}/cancel`, { method: "POST" }),
  deleteResults: (urls: string[]) =>
    request("/results/delete", { method: "POST", body: JSON.stringify({ urls }) }),
  prepareUrls: (fundUrls: string[]) =>
    request("/scrape/prepare", { method: "POST", body: JSON.stringify({ fund_urls: fundUrls }) }),
  refreshResults: () => request("/results/refresh", { method: "POST", timeoutMs: 60000 }),
  updateOpenAIKey: (apiKey: string) =>
    request("/settings/openai", {
      method: "POST",
      body: JSON.stringify({ openai_api_key: apiKey }),
    }),

  // Admin
  adminOrg: () => request<any>("/admin/org"),
  adminUpdateOrg: (data: Record<string, any>) =>
    request<any>("/admin/org", { method: "PUT", body: JSON.stringify(data) }),
  adminUsers: () => request<any[]>("/admin/users"),
  adminSetUserRole: (userId: string, role: "user" | "superuser") =>
    request(`/admin/users/${userId}/role`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  adminCreateUser: (email: string, password: string, role: "user" | "superuser" = "user") =>
    request<{ id: string; email: string; role: string }>("/admin/users", {
      method: "POST",
      body: JSON.stringify({ email, password, role }),
    }),
  adminTokens: () => request<any[]>("/admin/tokens"),
  adminSetOpenAIKey: (key: string) =>
    request("/admin/tokens/openai", {
      method: "POST",
      body: JSON.stringify({ openai_api_key: key }),
    }),
  adminSetSamGovKey: (key: string) =>
    request("/admin/tokens/sam_gov", {
      method: "POST",
      body: JSON.stringify({ sam_gov_api_key: key }),
    }),
  adminSetBraveKey: (key: string) =>
    request("/admin/tokens/brave_search", {
      method: "POST",
      body: JSON.stringify({ brave_search_api_key: key }),
    }),

  // Stats
  stats: () => request<DashboardStats>("/stats"),

  // Discovery
  discoveryConfig: () => request<any>("/discovery/config"),
  updateDiscoveryConfig: (data: any) =>
    request("/discovery/config", { method: "PUT", body: JSON.stringify(data) }),
  triggerDiscoveryRun: () =>
    request<{ id: string }>("/discovery/run", { method: "POST", timeoutMs: 60000 }),
  discoveryRuns: (limit = 20) =>
    request<any[]>(`/discovery/runs?limit=${limit}`),
  discoveryRunStatus: (runId: string) =>
    request<any>(`/discovery/runs/${runId}`),
  discoveryRunProgress: (runId: string) =>
    request<DiscoveryProgress>(`/discovery/runs/${runId}/progress`),
  cancelDiscoveryRun: (runId: string) =>
    request<DiscoveryProgress>(`/discovery/runs/${runId}/cancel`, { method: "POST" }),
  discoveryRunScrapedFunds: (runId: string) =>
    request<ScrapedFundResult[]>(`/discovery/runs/${runId}/scraped-funds`),

  // Import triggers
  triggerBMFImport: () =>
    request("/discovery/import/bmf", { method: "POST" }),
  triggerGrantsGovImport: () =>
    request("/discovery/import/grants-gov", { method: "POST" }),
  discoveryImportStatus: () =>
    request<DiscoveryImportStatus>("/discovery/import/status"),
};

// ── Import status shape ──────────────────────────────────────────────────────

export type DiscoveryImportStatus = {
  bmf_last_imported_at: string | null;
  grants_gov_last_imported_at: string | null;
  bmf_funders_total: number;
  bmf_funders_unscraped: number;
  grant_opportunities_total: number;
  grant_opportunities_open: number;
};

// ── Dashboard stats shape ─────────────────────────────────────────────────────

export type DashboardStats = {
  funds: {
    total: number;
    by_eligibility: Record<string, number>;
    by_grant_type: Record<string, number>;
    by_discovery_source: Record<string, number>;
    added_last_7d: number;
  };
  discovery: {
    last_run: {
      id: string;
      status: string;
      urls_discovered: number;
      urls_new: number;
      started_at: string | null;
      trigger: string;
    } | null;
    total_runs: number;
    total_urls_found: number;
  };
  org: {
    name: string | null;
    state: string | null;
    profile_complete: boolean;
    missing_fields: string[];
  };
};

// ── Scrape job status shape ───────────────────────────────────────────────────

export type JobStatusResponse = {
  job_id: string;
  done: boolean;
  progress_percent: number;
  total_urls: number;
  completed_urls: number;
  current_url?: string | null;
  current_elapsed_seconds: number;
  total_elapsed_seconds: number;
  started_at?: number | null;
  finished_at?: number | null;
  errors: Array<{ url: string; message: string }>;
};

// ── Discovery scraped-fund result shape ─────────────────────────────────────

export type ScrapedFundResult = {
  fund_url: string;
  funder_name?: string | null;
  eligibility?: string | null;
  grant_type?: string | null;
  discovery_source?: string | null;
};

// ── Discovery progress response shape ────────────────────────────────────────

export type SourceProgress = {
  name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | string;
  urls_found: number;
  urls_new: number;
  documents_found: number;
  current_action?: string | null;
  error?: string | null;
  started_at?: number | null;
  finished_at?: number | null;
};

export type DiscoveryProgress = {
  run_id: string;
  status: "running" | "running_docs" | "completed" | "failed" | "cancelled" | string;
  sources: Record<string, SourceProgress>;
  urls_discovered: number;
  urls_new: number;
  documents_submitted: number;
  documents_downloaded: number;
  documents_extracted: number;
  documents_skipped_dedup: number;
  documents_errors: number;
  scrape_job_id?: string | null;
  latest_results: Array<{ url: string; funder_name?: string; source?: string }>;
  started_at?: number | null;
  finished_at?: number | null;
  error?: string | null;
  elapsed_seconds: number;
  live: boolean;
};
