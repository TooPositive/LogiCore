"use client";

import { useState, useCallback } from "react";
import {
  FileSearch,
  Database,
  Scale,
  UserCheck,
  CheckCircle2,
  XCircle,
  Clock,
  Euro,
  Bot,
  Timer,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import type {
  AuditInvoice,
  AuditContractRate,
  AuditDiscrepancy,
  AuditStatus,
  DiscrepancyBand,
} from "@/lib/types";

// ── Workflow step definitions ──

interface WorkflowStep {
  key: AuditStatus;
  label: string;
  icon: typeof FileSearch;
}

const WORKFLOW_STEPS: WorkflowStep[] = [
  { key: "reading_contracts", label: "Reader", icon: FileSearch },
  { key: "querying_invoices", label: "SQL Agent", icon: Database },
  { key: "comparing", label: "Auditor", icon: Scale },
  { key: "awaiting_approval", label: "HITL Gate", icon: UserCheck },
  { key: "approved", label: "Complete", icon: CheckCircle2 },
];

const STEP_ORDER: AuditStatus[] = [
  "idle",
  "reading_contracts",
  "querying_invoices",
  "comparing",
  "awaiting_approval",
  "approved",
  "auto_approved",
  "rejected",
];

function stepIndex(status: AuditStatus): number {
  if (status === "auto_approved") return STEP_ORDER.indexOf("approved");
  if (status === "rejected") return STEP_ORDER.indexOf("awaiting_approval");
  return STEP_ORDER.indexOf(status);
}

// ── Band color utilities ──

function bandColor(band: DiscrepancyBand) {
  switch (band) {
    case "auto_approve":
      return "text-emerald-400 border-emerald-500/30 bg-emerald-500/10";
    case "investigate":
      return "text-amber-400 border-amber-500/30 bg-amber-500/10";
    case "escalate":
      return "text-orange-400 border-orange-500/30 bg-orange-500/10";
    case "critical":
      return "text-red-400 border-red-500/30 bg-red-500/10";
  }
}

function bandLabel(band: DiscrepancyBand) {
  switch (band) {
    case "auto_approve":
      return "AUTO APPROVE";
    case "investigate":
      return "INVESTIGATE";
    case "escalate":
      return "ESCALATE";
    case "critical":
      return "CRITICAL";
  }
}

// ── Demo data ──

interface DemoScenario {
  id: string;
  label: string;
  invoice: AuditInvoice;
  rates: AuditContractRate[];
  discrepancies: AuditDiscrepancy[];
  maxBand: DiscrepancyBand;
  autoApprove: boolean;
  costEur: number;
  durationS: number;
}

const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "INV-2024-00891",
    label: "EuroFreight — Clean (Auto-approve)",
    invoice: {
      invoice_id: "INV-2024-00891",
      vendor: "EuroFreight Sp. z o.o.",
      contract_id: "EF-2024-0891",
      issue_date: "2026-03-15",
      total_eur: 3229.60,
      line_items: [
        { description: "Warsaw-Berlin (580km)", distance_km: 580, unit_price: 1.82, total: 1055.60, cargo_type: "general" },
        { description: "Gdansk-Prague (720km)", distance_km: 720, unit_price: 1.88, total: 1353.60, cargo_type: "cross-border" },
        { description: "Krakow-Vienna (460km)", distance_km: 460, unit_price: 1.85, total: 851.00, cargo_type: "cross-border" },
      ],
    },
    rates: [
      { rate: 1.80, currency: "EUR", unit: "km", cargo_type: "general", min_volume: 100, source_doc: "EF-2024-0891 Section 4.1" },
      { rate: 1.85, currency: "EUR", unit: "km", cargo_type: "cross-border", min_volume: 100, source_doc: "EF-2024-0891 Section 4.2" },
    ],
    discrepancies: [
      { line_item: "Warsaw-Berlin (580km)", expected_total: 1044.00, actual_total: 1055.60, difference_eur: 11.60, pct: 1.1, band: "auto_approve" },
      { line_item: "Gdansk-Prague (720km)", expected_total: 1332.00, actual_total: 1353.60, difference_eur: 21.60, pct: 1.6, band: "auto_approve" },
      { line_item: "Krakow-Vienna (460km)", expected_total: 851.00, actual_total: 851.00, difference_eur: 0.00, pct: 0.0, band: "auto_approve" },
    ],
    maxBand: "auto_approve",
    autoApprove: true,
    costEur: 0.008,
    durationS: 2.1,
  },
  {
    id: "INV-2024-01247",
    label: "TransPol — Overcharge (Critical)",
    invoice: {
      invoice_id: "INV-2024-01247",
      vendor: "TransPol Logistics S.A.",
      contract_id: "TP-2024-1247",
      issue_date: "2026-03-18",
      total_eur: 3562.00,
      line_items: [
        { description: "Warsaw-Gdansk (340km)", distance_km: 340, unit_price: 2.15, total: 731.00, cargo_type: "standard" },
        { description: "Poznan-Wroclaw (180km)", distance_km: 180, unit_price: 2.40, total: 432.00, cargo_type: "standard" },
        { description: "Cold chain Gdansk-Hamburg (650km)", distance_km: 650, unit_price: 3.85, total: 2502.50, cargo_type: "cold_chain" },
      ],
    },
    rates: [
      { rate: 1.95, currency: "EUR", unit: "km", cargo_type: "standard", min_volume: 50, source_doc: "TP-2024-1247 Section 3.1" },
      { rate: 3.20, currency: "EUR", unit: "km", cargo_type: "cold_chain", min_volume: 50, source_doc: "TP-2024-1247 Section 3.4" },
    ],
    discrepancies: [
      { line_item: "Warsaw-Gdansk (340km)", expected_total: 663.00, actual_total: 731.00, difference_eur: 68.00, pct: 10.3, band: "escalate" },
      { line_item: "Poznan-Wroclaw (180km)", expected_total: 351.00, actual_total: 432.00, difference_eur: 81.00, pct: 23.1, band: "critical" },
      { line_item: "Cold chain Gdansk-Hamburg (650km)", expected_total: 2080.00, actual_total: 2502.50, difference_eur: 422.50, pct: 20.3, band: "critical" },
    ],
    maxBand: "critical",
    autoApprove: false,
    costEur: 0.042,
    durationS: 3.8,
  },
  {
    id: "INV-2024-00456",
    label: "Baltic Transport — Minor Issue (Investigate)",
    invoice: {
      invoice_id: "INV-2024-00456",
      vendor: "Baltic Transport Sp. z o.o.",
      contract_id: "BT-2024-0456",
      issue_date: "2026-03-20",
      total_eur: 3836.50,
      line_items: [
        { description: "Szczecin-Berlin (130km)", distance_km: 130, unit_price: 2.05, total: 266.50, cargo_type: "standard" },
        { description: "Gdynia-Stockholm ferry+road (850km)", distance_km: 850, unit_price: 4.20, total: 3570.00, cargo_type: "ferry_road" },
      ],
    },
    rates: [
      { rate: 1.95, currency: "EUR", unit: "km", cargo_type: "standard", min_volume: 50, source_doc: "BT-2024-0456 Section 2.1" },
      { rate: 4.10, currency: "EUR", unit: "km", cargo_type: "ferry_road", min_volume: 50, source_doc: "BT-2024-0456 Section 2.3" },
    ],
    discrepancies: [
      { line_item: "Szczecin-Berlin (130km)", expected_total: 253.50, actual_total: 266.50, difference_eur: 13.00, pct: 5.1, band: "investigate" },
      { line_item: "Gdynia-Stockholm ferry+road (850km)", expected_total: 3485.00, actual_total: 3570.00, difference_eur: 85.00, pct: 2.4, band: "investigate" },
    ],
    maxBand: "investigate",
    autoApprove: false,
    costEur: 0.025,
    durationS: 3.2,
  },
];

// ── Workflow Steps Visualization ──

function WorkflowProgress({ status }: { status: AuditStatus }) {
  const currentIdx = stepIndex(status);

  return (
    <div className="flex items-center justify-between">
      {WORKFLOW_STEPS.map((step, i) => {
        const stepPos = stepIndex(step.key);
        const isComplete = currentIdx > stepPos;
        const isActive = currentIdx === stepPos;
        // For auto_approved, show the last step as complete
        const isFinalComplete =
          (status === "auto_approved" || status === "approved") &&
          step.key === "approved";
        const done = isComplete || isFinalComplete;
        // For rejected, mark the HITL Gate as active/red
        const isRejected = status === "rejected" && step.key === "awaiting_approval";

        const Icon = step.icon;

        let dotClasses = "border-zinc-700 bg-zinc-900 text-zinc-600";
        if (done) {
          dotClasses = "border-emerald-500/50 bg-emerald-500/20 text-emerald-400";
        } else if (isRejected) {
          dotClasses = "border-red-500/50 bg-red-500/20 text-red-400";
        } else if (isActive) {
          dotClasses = "border-emerald-400 bg-emerald-500/20 text-emerald-400 animate-pulse";
        }

        let lineClasses = "bg-zinc-700";
        if (done || (isActive && i > 0)) {
          lineClasses = "bg-emerald-500/50";
        }

        return (
          <div key={step.key} className="flex items-center flex-1 last:flex-none">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all ${dotClasses}`}
              >
                <Icon className="h-4 w-4" />
              </div>
              <span
                className={`mt-1.5 text-[10px] font-medium ${
                  done || isActive ? "text-zinc-300" : isRejected ? "text-red-400" : "text-zinc-600"
                }`}
              >
                {step.label}
              </span>
            </div>
            {i < WORKFLOW_STEPS.length - 1 && (
              <div className={`mx-2 h-0.5 flex-1 rounded-full transition-all ${lineClasses}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main Page ──

export default function AuditPage() {
  const [selectedId, setSelectedId] = useState(DEMO_SCENARIOS[0].id);
  const [status, setStatus] = useState<AuditStatus>("idle");
  const [running, setRunning] = useState(false);

  const scenario = DEMO_SCENARIOS.find((s) => s.id === selectedId)!;
  const currentStep = stepIndex(status);

  const startAudit = useCallback(() => {
    if (running) return;
    setRunning(true);
    setStatus("reading_contracts");

    const steps: AuditStatus[] = [
      "reading_contracts",
      "querying_invoices",
      "comparing",
      scenario.autoApprove ? "auto_approved" : "awaiting_approval",
    ];

    steps.forEach((s, i) => {
      if (i === 0) return; // already set
      setTimeout(() => setStatus(s), i * 800);
    });

    setTimeout(
      () => setRunning(false),
      (steps.length - 1) * 800
    );
  }, [running, scenario.autoApprove]);

  const handleApprove = () => setStatus("approved");
  const handleReject = () => setStatus("rejected");

  const resetAudit = () => {
    setStatus("idle");
    setRunning(false);
  };

  const isFinished =
    status === "approved" ||
    status === "auto_approved" ||
    status === "rejected";

  // Visibility gates: content appears progressively
  const showRates = currentStep >= stepIndex("reading_contracts");
  const showLineItems = currentStep >= stepIndex("querying_invoices");
  const showDiscrepancies = currentStep >= stepIndex("comparing");
  const showHitl = status === "awaiting_approval";
  const showSummary = isFinished;

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Freight Audit Engine
          </h1>
          <p className="text-sm text-zinc-500">
            Multi-agent invoice audit with human-in-the-loop gate
          </p>
        </div>
        <Badge
          variant="outline"
          className="border-emerald-500/30 text-emerald-400"
        >
          3 Agents · HITL Gate
        </Badge>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3">
        <Select
          value={selectedId}
          onValueChange={(v) => {
            setSelectedId(v);
            resetAudit();
          }}
        >
          <SelectTrigger className="w-96 border-zinc-700 bg-zinc-900">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="border-zinc-700 bg-zinc-900">
            {DEMO_SCENARIOS.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                <div className="flex items-center gap-2">
                  <span>{s.label}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          onClick={startAudit}
          disabled={running || (status !== "idle")}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          Start Audit
        </Button>

        {status !== "idle" && (
          <Button
            variant="outline"
            onClick={resetAudit}
            disabled={running}
            className="border-zinc-700 text-zinc-400 hover:text-zinc-100"
          >
            Reset
          </Button>
        )}

        {/* Status badge */}
        {status !== "idle" && (
          <Badge
            variant="outline"
            className={
              status === "approved" || status === "auto_approved"
                ? "border-emerald-500/30 text-emerald-400"
                : status === "rejected"
                  ? "border-red-500/30 text-red-400"
                  : status === "awaiting_approval"
                    ? "border-amber-500/30 text-amber-400"
                    : "border-blue-500/30 text-blue-400"
            }
          >
            {status === "auto_approved"
              ? "Auto-Approved"
              : status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </Badge>
        )}
      </div>

      {/* Workflow Progress */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardContent className="py-5">
          <WorkflowProgress status={status} />
        </CardContent>
      </Card>

      {/* Two-Column Layout */}
      {status !== "idle" && (
        <div className="grid grid-cols-5 gap-4">
          {/* Left: Invoice Details (60%) */}
          <div className="col-span-3 space-y-4">
            {/* Invoice Header */}
            <Card className="border-zinc-800 bg-zinc-900">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-medium text-zinc-300">
                    Invoice Details
                  </CardTitle>
                  <Badge variant="outline" className="border-zinc-700 text-xs text-zinc-400">
                    {scenario.invoice.invoice_id}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Vendor</span>
                    <span className="text-zinc-200">{scenario.invoice.vendor}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Contract</span>
                    <span className="font-mono text-zinc-200">{scenario.invoice.contract_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Issue Date</span>
                    <span className="text-zinc-200">{scenario.invoice.issue_date}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Total</span>
                    <span className="font-mono font-bold text-zinc-100">
                      EUR {scenario.invoice.total_eur.toFixed(2)}
                    </span>
                  </div>
                </div>

                {/* Line Items Table */}
                {showLineItems && (
                  <>
                    <Separator className="bg-zinc-800" />
                    <Table>
                      <TableHeader>
                        <TableRow className="border-zinc-800">
                          <TableHead className="text-zinc-500">Route</TableHead>
                          <TableHead className="text-zinc-500 text-right">Distance</TableHead>
                          <TableHead className="text-zinc-500 text-right">EUR/km</TableHead>
                          <TableHead className="text-zinc-500 text-right">Total</TableHead>
                          <TableHead className="text-zinc-500">Cargo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {scenario.invoice.line_items.map((item) => (
                          <TableRow key={item.description} className="border-zinc-800">
                            <TableCell className="text-xs text-zinc-300">
                              {item.description}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs text-zinc-400">
                              {item.distance_km} km
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs text-zinc-400">
                              {item.unit_price.toFixed(2)}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs text-zinc-100">
                              EUR {item.total.toFixed(2)}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant="outline"
                                className="border-zinc-700 text-[10px] text-zinc-400"
                              >
                                {item.cargo_type}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right: Rates + Discrepancies (40%) */}
          <div className="col-span-2 space-y-4">
            {/* Contract Rates */}
            {showRates && (
              <Card className="border-zinc-800 bg-zinc-900">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium text-zinc-300">
                    Contract Rates
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {scenario.rates.map((rate) => (
                    <div
                      key={rate.cargo_type}
                      className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-2"
                    >
                      <div>
                        <p className="text-xs font-medium text-zinc-300">
                          {rate.cargo_type.replace(/_/g, " ")}
                        </p>
                        <p className="text-[10px] text-zinc-600">{rate.source_doc}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-mono text-sm font-bold text-emerald-400">
                          EUR {rate.rate.toFixed(2)}/{rate.unit}
                        </p>
                        <p className="text-[10px] text-zinc-600">
                          min {rate.min_volume} {rate.unit}
                        </p>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Discrepancy Analysis */}
            {showDiscrepancies && (
              <Card className="border-zinc-800 bg-zinc-900">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-medium text-zinc-300">
                      Discrepancy Analysis
                    </CardTitle>
                    <Badge
                      variant="outline"
                      className={`text-[10px] ${bandColor(scenario.maxBand)}`}
                    >
                      Max: {bandLabel(scenario.maxBand)}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  {scenario.discrepancies.map((d) => (
                    <div
                      key={d.line_item}
                      className="rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-zinc-300">{d.line_item}</span>
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${bandColor(d.band)}`}
                        >
                          {bandLabel(d.band)}
                        </Badge>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between text-[11px]">
                        <span className="text-zinc-500">
                          Expected: <span className="font-mono text-zinc-400">EUR {d.expected_total.toFixed(2)}</span>
                        </span>
                        <span className="text-zinc-500">
                          Actual: <span className="font-mono text-zinc-400">EUR {d.actual_total.toFixed(2)}</span>
                        </span>
                      </div>
                      <div className="mt-1 flex items-center justify-between">
                        <span className="font-mono text-xs font-bold text-zinc-200">
                          {d.difference_eur > 0 ? "+" : ""}EUR {d.difference_eur.toFixed(2)}
                        </span>
                        <span
                          className={`font-mono text-xs font-bold ${
                            d.pct <= 2
                              ? "text-emerald-400"
                              : d.pct <= 5
                                ? "text-amber-400"
                                : d.pct <= 15
                                  ? "text-orange-400"
                                  : "text-red-400"
                          }`}
                        >
                          {d.pct > 0 ? "+" : ""}{d.pct.toFixed(1)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* HITL Gate Panel */}
      {showHitl && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="py-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-amber-500/20 p-2">
                  <UserCheck className="h-5 w-5 text-amber-400" />
                </div>
                <div>
                  <p className="text-sm font-medium text-amber-400">
                    Discrepancy exceeds threshold. Human approval required.
                  </p>
                  <p className="text-xs text-zinc-500">
                    Max discrepancy band:{" "}
                    <span
                      className={`font-bold ${
                        scenario.maxBand === "critical" ? "text-red-400" : "text-amber-400"
                      }`}
                    >
                      {bandLabel(scenario.maxBand)}
                    </span>
                    {" "}— Total overcharge: EUR{" "}
                    {scenario.discrepancies
                      .reduce((sum, d) => sum + d.difference_eur, 0)
                      .toFixed(2)}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={handleApprove}
                  className="bg-emerald-600 hover:bg-emerald-700"
                  size="sm"
                >
                  <CheckCircle2 className="mr-1 h-4 w-4" />
                  Approve
                </Button>
                <Button
                  onClick={handleReject}
                  variant="outline"
                  className="border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-300"
                  size="sm"
                >
                  <XCircle className="mr-1 h-4 w-4" />
                  Reject
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Auto-Approved Banner */}
      {status === "auto_approved" && (
        <Card className="border-emerald-500/30 bg-emerald-500/5">
          <CardContent className="flex items-center gap-3 py-4">
            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            <div>
              <p className="text-sm font-medium text-emerald-400">
                All discrepancies within threshold — auto-approved
              </p>
              <p className="text-xs text-zinc-500">
                No human review required. Max deviation:{" "}
                {Math.max(...scenario.discrepancies.map((d) => d.pct)).toFixed(1)}%
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Rejected Banner */}
      {status === "rejected" && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardContent className="flex items-center gap-3 py-4">
            <XCircle className="h-5 w-5 text-red-400" />
            <div>
              <p className="text-sm font-medium text-red-400">
                Invoice rejected — flagged for vendor dispute
              </p>
              <p className="text-xs text-zinc-500">
                Overcharge of EUR{" "}
                {scenario.discrepancies
                  .reduce((sum, d) => sum + d.difference_eur, 0)
                  .toFixed(2)}{" "}
                will be escalated to procurement
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary Card */}
      {showSummary && (
        <Card className="border-zinc-800 bg-zinc-900">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-zinc-300">
              Audit Summary
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-5 gap-4">
              {[
                {
                  label: "AI Cost",
                  value: `EUR ${scenario.costEur.toFixed(3)}`,
                  icon: Euro,
                  color: "text-emerald-400",
                  bg: "bg-emerald-500/10",
                },
                {
                  label: "Processing Time",
                  value: `${scenario.durationS}s`,
                  icon: Clock,
                  color: "text-blue-400",
                  bg: "bg-blue-500/10",
                },
                {
                  label: "Agents Used",
                  value: "3",
                  icon: Bot,
                  color: "text-purple-400",
                  bg: "bg-purple-500/10",
                },
                {
                  label: "Manual Equivalent",
                  value: "~45 min",
                  icon: Timer,
                  color: "text-amber-400",
                  bg: "bg-amber-500/10",
                },
                {
                  label: "Speed Advantage",
                  value: "145x faster",
                  icon: TrendingUp,
                  color: "text-emerald-400",
                  bg: "bg-emerald-500/10",
                },
              ].map(({ label, value, icon: Icon, color, bg }) => (
                <div key={label} className="flex items-center gap-3">
                  <div className={`rounded-lg p-2 ${bg}`}>
                    <Icon className={`h-4 w-4 ${color}`} />
                  </div>
                  <div>
                    <p className="text-[10px] text-zinc-500">{label}</p>
                    <p className={`font-mono text-sm font-bold ${color}`}>
                      {value}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
