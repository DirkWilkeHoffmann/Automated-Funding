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
};
