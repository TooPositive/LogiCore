// ── Map types ──

export type TruckStatus = "alert" | "cold_chain" | "stopped" | "idle" | "moving";

export type TileMode = "dark" | "satellite";

export interface MapFilter {
  statuses: Set<TruckStatus>;
  searchQuery: string;
}

export interface GeofenceDefinition {
  id: string;
  city: string;
  country: string;
  lat: number;
  lng: number;
  radiusMeters: number;
  warehouseType: "standard" | "cold_storage";
  label: string;
}

export interface RouteDefinition {
  name: string;
  waypoints: [number, number][];
  color: string;
}

// ── Simulator types ──

export interface GpsPing {
  truck_id: string;
  lat: number;
  lng: number;
  speed_kmh: number;
  engine_on: boolean;
  route: string;
  client: string;
  timestamp: string;
}

export interface TemperatureReading {
  truck_id: string;
  sensor_id: string;
  temp_celsius: number;
  setpoint_celsius: number;
  cargo_type: string;
  cargo_value_eur: number;
  timestamp: string;
}

export interface SimulatorStatus {
  total_trucks: number;
  refrigerated: number;
  shard_count: number;
  active_anomalies: { truck_id: string; anomaly: string }[];
}

// ── Fleet API types ──

export type AlertSeverity = "low" | "medium" | "high" | "critical";
export type AlertType =
  | "temperature_spike"
  | "temperature_drift"
  | "gps_deviation"
  | "speed_anomaly"
  | "heartbeat_timeout";

export interface FleetAlert {
  alert_id: string;
  truck_id: string;
  alert_type: AlertType;
  severity: AlertSeverity;
  details: string;
  timestamp: string;
  resolved: boolean;
  cargo_value_eur?: number;
}

export interface FleetStatus {
  total_trucks: number;
  active_alerts: number;
  consumer_health: {
    running: boolean;
    messages_processed: number;
    errors: number;
    last_message_at: string | null;
  };
}

// ── Search types ──

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  title: string;
  content: string;
  score: number;
  department_id: string;
  clearance_level: number;
  metadata?: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  user_id: string;
  total: number;
}

// ── Analytics types ──

export interface CostsResponse {
  total_cost: number;
  total_queries: number;
  avg_cost_per_query: number;
  cache_hit_rate: number;
  by_agent: Record<string, { cost: number; queries: number; tokens: number }>;
  period: string;
}

export interface QualityResponse {
  context_precision: number;
  faithfulness: number;
  answer_relevancy: number;
  last_eval: string | null;
  dataset_size: number;
  passes_gate: boolean;
}

export interface ProviderState {
  name: string;
  state: "closed" | "open" | "half_open";
  total_calls: number;
  total_failures: number;
  trips: number;
}

export interface ResilienceResponse {
  provider_states: ProviderState[];
  routing_stats: Record<string, number>;
}

// ── Compliance types ──

export interface AuditEntry {
  id: string;
  timestamp: string;
  user_id: string;
  query_text: string;
  model_version: string;
  log_level: string;
  cost_eur: number;
  is_degraded: boolean;
  response_text?: string;
}

export interface ComplianceReport {
  period_start: string;
  period_end: string;
  total_entries: number;
  models_used: string[];
  unique_users: number;
  hitl_count: number;
  total_cost_eur: number;
  entries_by_level: Record<string, number>;
}

export interface HashChainVerify {
  valid: boolean;
  broken_at: number | null;
}

export interface LineageRecord {
  document_id: string;
  document_versions: { version: number; hash: string; timestamp: string }[];
  chunk_versions: { chunk_id: string; hash: string; qdrant_point_id: string }[];
  embedding_model: string;
}

// ── Audit types (Phase 3) ──

export interface AuditLineItem {
  description: string;
  distance_km: number;
  unit_price: number;
  total: number;
  cargo_type: string;
}

export interface AuditInvoice {
  invoice_id: string;
  vendor: string;
  contract_id: string;
  issue_date: string;
  total_eur: number;
  line_items: AuditLineItem[];
}

export interface AuditContractRate {
  rate: number;
  currency: string;
  unit: string;
  cargo_type: string;
  min_volume: number;
  source_doc: string;
}

export type DiscrepancyBand = "auto_approve" | "investigate" | "escalate" | "critical";

export interface AuditDiscrepancy {
  line_item: string;
  expected_total: number;
  actual_total: number;
  difference_eur: number;
  pct: number;
  band: DiscrepancyBand;
}

export type AuditStatus =
  | "idle"
  | "reading_contracts"
  | "querying_invoices"
  | "comparing"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "auto_approved";

export interface AuditRun {
  run_id: string;
  invoice: AuditInvoice;
  rates: AuditContractRate[];
  discrepancies: AuditDiscrepancy[];
  status: AuditStatus;
  cost_eur: number;
  duration_s: number;
  max_band: DiscrepancyBand;
}

// ── Drift & Bias types (Phase 5) ──

export type DriftSeverity = "green" | "yellow" | "red";

export interface DriftAlert {
  metric: string;
  baseline: number;
  current: number;
  delta_pct: number;
  severity: DriftSeverity;
}

export interface JudgeBias {
  judge_model: string;
  position_bias_rate: number;
  verbosity_bias_rate: number;
  self_preference_rate: number;
  human_correlation: number;
  total_comparisons: number;
  gate_status: "pass" | "halt";
}

// ── Provider types (Phase 6 & 7) ──

export interface ProviderComparison {
  name: string;
  quality_stars: number;
  latency_ms: number;
  cost_per_1k: number;
  privacy: "cloud" | "local";
}

export interface ModelRoutingEntry {
  model: string;
  label: string;
  pct: number;
  queries: number;
}
