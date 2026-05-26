"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

export type DiscoverySources = {
  propublica: boolean;
  grants_gov: boolean;
  sam_gov: boolean;
  web_search: boolean;
  federal_register: boolean;
  state_portals: boolean;
  usaspending: boolean;
  candid: boolean;
  philanthropy_digest: boolean;
  irs_bmf: boolean;
  grants_gov_db: boolean;
};

export type ImportConfig = {
  bmf_min_asset_code: number;
  bmf_ntee_prefixes: string[];
  bmf_batch_size: number;
  grants_gov_close_days: number;
  bmf_last_imported_at: string | null;
  grants_gov_last_imported_at: string | null;
};

export type DiscoveryConfig = {
  id?: string;
  enabled: boolean;
  cron_expression: string;
  states: string[];
  keywords: string[];
  sources: DiscoverySources;
  max_per_source: number;
  documents_per_run: number;
  import_config: ImportConfig;
  updated_at?: string;
};

export type ScheduleMode = "daily" | "weekly" | "monthly" | "custom";

export const DEFAULT_SOURCES: DiscoverySources = {
  propublica: true,
  grants_gov: true,
  sam_gov: false,
  web_search: true,
  federal_register: true,
  state_portals: true,
  usaspending: false,
  candid: false,
  philanthropy_digest: false,
  irs_bmf: true,
  grants_gov_db: true,
};

const DEFAULT_IMPORT_CONFIG: ImportConfig = {
  bmf_min_asset_code: 7,
  bmf_ntee_prefixes: [],
  bmf_batch_size: 50,
  grants_gov_close_days: 90,
  bmf_last_imported_at: null,
  grants_gov_last_imported_at: null,
};

const DEFAULT_CONFIG: DiscoveryConfig = {
  enabled: false,
  cron_expression: "0 2 * * 1",
  states: [],
  keywords: [],
  sources: DEFAULT_SOURCES,
  max_per_source: 100,
  documents_per_run: 200,
  import_config: DEFAULT_IMPORT_CONFIG,
};

export function parseCronToSchedule(expr: string) {
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return { mode: "custom" as ScheduleMode, hour: 2, minute: 0, dow: 1, dom: 1 };
  const [min, hr, dom, , dow] = p;
  const hour = parseInt(hr, 10), minute = parseInt(min, 10);
  const h = isNaN(hour) ? 2 : hour, m = isNaN(minute) ? 0 : minute;
  if (dow !== "*" && dom === "*")
    return { mode: "weekly" as ScheduleMode, hour: h, minute: m, dow: parseInt(dow, 10) || 1, dom: 1 };
  if (dom !== "*" && dow === "*")
    return { mode: "monthly" as ScheduleMode, hour: h, minute: m, dow: 1, dom: parseInt(dom, 10) || 1 };
  if (dow === "*" && dom === "*")
    return { mode: "daily" as ScheduleMode, hour: h, minute: m, dow: 1, dom: 1 };
  return { mode: "custom" as ScheduleMode, hour: h, minute: m, dow: 1, dom: 1 };
}

export function buildCron(mode: ScheduleMode, h: number, m: number, dow: number, dom: number, custom: string) {
  if (mode === "custom") return custom;
  if (mode === "daily") return `${m} ${h} * * *`;
  if (mode === "weekly") return `${m} ${h} * * ${dow}`;
  return `${m} ${h} ${dom} * *`;
}

export function describeSchedule(mode: ScheduleMode, h: number, m: number, dow: number, dom: number) {
  const DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const t = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")} UTC`;
  if (mode === "daily") return `Every day at ${t}`;
  if (mode === "weekly") return `Every ${DOW_NAMES[dow]} at ${t}`;
  if (mode === "monthly") return `Day ${dom} of every month at ${t}`;
  return "";
}

export type UseDiscoveryConfig = {
  config: DiscoveryConfig;
  setConfig: React.Dispatch<React.SetStateAction<DiscoveryConfig>>;
  schedMode: ScheduleMode;
  setSchedMode: (m: ScheduleMode) => void;
  schedHour: number;
  setSchedHour: (h: number) => void;
  schedMin: number;
  setSchedMin: (m: number) => void;
  schedDow: number;
  setSchedDow: (d: number) => void;
  schedDom: number;
  setSchedDom: (d: number) => void;
  customCron: string;
  setCustomCron: (c: string) => void;
  cron: string;
  schedDesc: string;
  loadError: string | null;
  saving: boolean;
  saveStatus: string | null;
  orgWarnings: string[];
  statesWarning: string | null;
  handleSave: () => Promise<void>;
};

export function useDiscoveryConfig(): UseDiscoveryConfig {
  const [config, setConfig] = useState<DiscoveryConfig>(DEFAULT_CONFIG);
  const [schedMode, setSchedMode] = useState<ScheduleMode>("weekly");
  const [schedHour, setSchedHour] = useState(2);
  const [schedMin, setSchedMin] = useState(0);
  const [schedDow, setSchedDow] = useState(1);
  const [schedDom, setSchedDom] = useState(1);
  const [customCron, setCustomCron] = useState("0 2 * * 1");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [orgWarnings, setOrgWarnings] = useState<string[]>([]);

  useEffect(() => {
    api
      .discoveryConfig()
      .then((c: DiscoveryConfig) => {
        setConfig({
          ...c,
          sources: { ...DEFAULT_SOURCES, ...c.sources },
          import_config: { ...DEFAULT_IMPORT_CONFIG, ...(c.import_config || {}) },
        });
        const s = parseCronToSchedule(c.cron_expression);
        setSchedMode(s.mode);
        setSchedHour(s.hour);
        setSchedMin(s.minute);
        setSchedDow(s.dow);
        setSchedDom(s.dom);
        setCustomCron(c.cron_expression);
      })
      .catch((e: any) => setLoadError(e.message || "Failed to load config"));

    api.adminOrg().then((org: any) => {
      const warnings: string[] = [];
      if (!org?.name) warnings.push("Organisation name is not set.");
      if (!org?.state) warnings.push("Organisation state is not set — discovery will search all 50 US states and geographic matching will be poor.");
      if (!org?.mission && !org?.services?.length) warnings.push("Mission or services are not set — keyword derivation will fall back to a generic query.");
      setOrgWarnings(warnings);
    }).catch(() => {
      setOrgWarnings(["Could not load organisation profile — eligibility scoring may be inaccurate."]);
    });
  }, []);

  useEffect(() => {
    const cron = buildCron(schedMode, schedHour, schedMin, schedDow, schedDom, customCron);
    setConfig((c) => ({ ...c, cron_expression: cron }));
  }, [schedMode, schedHour, schedMin, schedDow, schedDom, customCron]);

  const cron = buildCron(schedMode, schedHour, schedMin, schedDow, schedDom, customCron);
  const schedDesc = schedMode !== "custom"
    ? describeSchedule(schedMode, schedHour, schedMin, schedDow, schedDom)
    : "";

  const statesWarning = useMemo(
    () => config.states.length === 0
      ? "No states configured — discovery will use your organisation's home state (if set) or search all 50 US states, reducing geographic match accuracy."
      : null,
    [config.states]
  );

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus(null);
    try {
      const saved = await api.updateDiscoveryConfig(config);
      setConfig({
        ...saved,
        sources: { ...DEFAULT_SOURCES, ...saved.sources },
        import_config: { ...DEFAULT_IMPORT_CONFIG, ...(saved.import_config || {}) },
      });
      setSaveStatus("Configuration saved.");
    } catch (e: any) {
      setSaveStatus(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return {
    config, setConfig,
    schedMode, setSchedMode,
    schedHour, setSchedHour,
    schedMin, setSchedMin,
    schedDow, setSchedDow,
    schedDom, setSchedDom,
    customCron, setCustomCron,
    cron, schedDesc,
    loadError, saving, saveStatus,
    orgWarnings, statesWarning,
    handleSave,
  };
}
