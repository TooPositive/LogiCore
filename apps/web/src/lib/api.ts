import type {
  GpsPing,
  TemperatureReading,
  SimulatorStatus,
  FleetStatus,
  FleetAlert,
  SearchResponse,
  CostsResponse,
  QualityResponse,
  ResilienceResponse,
  AuditEntry,
  HashChainVerify,
  ComplianceReport,
  LineageRecord,
  AuditRun,
} from "./types";

// In the browser, use Next.js proxy rewrites to avoid CORS.
// /api/* → localhost:8080/api/*  (configured in next.config.ts)
// /simulator/* → localhost:8081/* (configured in next.config.ts)
const API = "";
const SIM = "/simulator";

async function get<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function post<T>(url: string, body?: unknown): Promise<T | null> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = `Server error (${res.status})`;
      try {
        const err = await res.json();
        if (err.detail) detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
      } catch {
        // ignore parse failure
      }
      throw new Error(detail);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof Error) throw e;
    return null;
  }
}

// ── Simulator ──

export const sim = {
  snapshot: () => get<GpsPing[]>(`${SIM}/fleet/snapshot`),
  temperatures: () => get<TemperatureReading[]>(`${SIM}/fleet/temperatures`),
  status: () => get<SimulatorStatus>(`${SIM}/fleet/status`),
  triggerTempSpike: (truckId = "truck-4721") =>
    post(`${SIM}/simulator/trigger/temperature-spike?truck_id=${truckId}`),
  triggerSpeedAnomaly: (truckId = "truck-0892") =>
    post(`${SIM}/simulator/trigger/speed-anomaly?truck_id=${truckId}`),
  triggerRouteDeviation: (truckId = "truck-1138") =>
    post(`${SIM}/simulator/trigger/route-deviation?truck_id=${truckId}`),
  reset: () => post(`${SIM}/simulator/reset`),
};

// ── Fleet API ──

export const fleet = {
  status: () => get<FleetStatus>(`${API}/api/v1/fleet/status`),
  alerts: (severity?: string) =>
    get<{ alerts: FleetAlert[]; total: number }>(
      `${API}/api/v1/fleet/alerts${severity ? `?severity=${severity}` : ""}`
    ),
  wsUrl: () => {
    // WebSocket can't go through Next.js rewrites, connect directly
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `ws://${host}:8080/api/v1/fleet/ws`;
  },
};

// ── Search ──

export const search = {
  query: (query: string, userId: string, topK = 5) =>
    post<SearchResponse>(`${API}/api/v1/search`, {
      query,
      user_id: userId,
      top_k: topK,
    }),
};

// ── Analytics ──

export const analytics = {
  costs: (period = "7d") =>
    get<CostsResponse>(`${API}/api/v1/analytics/costs?period=${period}`),
  quality: () => get<QualityResponse>(`${API}/api/v1/analytics/quality`),
  resilience: () =>
    get<ResilienceResponse>(`${API}/api/v1/analytics/resilience`),
};

// ── Compliance ──

export const compliance = {
  auditLog: (viewerRole = "admin") =>
    get<{ entries: AuditEntry[]; total: number }>(
      `${API}/api/v1/compliance/audit-log?viewer_role=${viewerRole}`
    ),
  hashChain: () =>
    get<HashChainVerify>(`${API}/api/v1/compliance/hash-chain/verify`),
  report: (viewerRole = "compliance_officer") =>
    get<ComplianceReport>(
      `${API}/api/v1/compliance/report?period_start=2024-01-01T00:00:00Z&period_end=2026-12-31T23:59:59Z&viewer_role=${viewerRole}`
    ),
  lineage: (documentId: string) =>
    get<LineageRecord>(`${API}/api/v1/compliance/lineage/${documentId}`),
};

// ── Audit (Phase 3) ──

export const audit = {
  start: (invoiceId: string) =>
    post<AuditRun>(`${API}/api/v1/audit/start`, { invoice_id: invoiceId }),
  status: (runId: string) =>
    get<AuditRun>(`${API}/api/v1/audit/${runId}/status`),
  approve: (runId: string, approved: boolean, reviewerId: string) =>
    post(`${API}/api/v1/audit/${runId}/approve`, {
      approved,
      reviewer_id: reviewerId,
    }),
};

// ── Health ──

export const health = {
  check: () =>
    get<{ status: string; version: string; service: string }>(
      `${API}/api/v1/health`
    ),
};
