"use client";

import { useEffect, useState } from "react";
import {
  Euro,
  Hash,
  Zap,
  Database,
  CircleDot,
  TrendingUp,
  ArrowDown,
  ShieldCheck,
  Info,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { analytics } from "@/lib/api";
import type {
  CostsResponse,
  QualityResponse,
  ResilienceResponse,
  DriftAlert,
  JudgeBias,
  ModelRoutingEntry,
  ProviderComparison,
} from "@/lib/types";

// ── Demo data ──

const demoCosts: CostsResponse = {
  total_cost: 2.47,
  total_queries: 842,
  avg_cost_per_query: 0.0029,
  cache_hit_rate: 0.34,
  by_agent: {
    "rag-search": { cost: 1.12, queries: 520, tokens: 385000 },
    "audit-workflow": { cost: 0.85, queries: 180, tokens: 290000 },
    "fleet-guardian": { cost: 0.32, queries: 95, tokens: 112000 },
    "compliance-report": { cost: 0.18, queries: 47, tokens: 64000 },
  },
  period: "7d",
};

const demoQuality: QualityResponse = {
  context_precision: 0.87,
  faithfulness: 0.92,
  answer_relevancy: 0.84,
  last_eval: "2026-03-27T08:00:00Z",
  dataset_size: 52,
  passes_gate: true,
};

const demoResilience: ResilienceResponse = {
  provider_states: [
    { name: "Azure OpenAI", state: "closed", total_calls: 1842, total_failures: 3, trips: 0 },
    { name: "Ollama (Local)", state: "closed", total_calls: 95, total_failures: 0, trips: 0 },
    { name: "Azure OpenAI (Fallback)", state: "closed", total_calls: 3, total_failures: 0, trips: 0 },
  ],
  routing_stats: { primary: 1842, fallback: 3, local: 95 },
};

const demoRouting: ModelRoutingEntry[] = [
  { model: "gpt-5-nano", label: "Simple queries", pct: 72, queries: 606 },
  { model: "gpt-5-mini", label: "Standard", pct: 18, queries: 152 },
  { model: "gpt-5.2", label: "Complex reasoning", pct: 8, queries: 67 },
  { model: "ollama-qwen3:8b", label: "Air-gapped", pct: 2, queries: 17 },
];

const demoDrift: (DriftAlert & { description: string })[] = [
  { metric: "Context Precision", baseline: 0.89, current: 0.87, delta_pct: -2.2, severity: "yellow", description: "Measures whether retrieved chunks are actually relevant to the query. Computed by comparing retrieved context against ground-truth relevant passages using LLM-as-judge scoring." },
  { metric: "Faithfulness", baseline: 0.91, current: 0.92, delta_pct: 1.1, severity: "green", description: "Measures whether the generated answer is factually grounded in the retrieved context — no hallucinated claims. Each statement in the answer is verified against the source chunks." },
  { metric: "Answer Relevancy", baseline: 0.86, current: 0.84, delta_pct: -2.3, severity: "yellow", description: "Measures whether the answer directly addresses the user's question. Scored by generating hypothetical questions from the answer and comparing them to the original query via embedding similarity." },
  { metric: "Hallucination Rate", baseline: 0.03, current: 0.02, delta_pct: -33.3, severity: "green", description: "Percentage of generated statements that cannot be traced to any retrieved source document. Lower is better. Measured by claim-level extraction and source verification." },
];

const demoBias: JudgeBias = {
  judge_model: "gpt-5-mini",
  position_bias_rate: 0.042,
  verbosity_bias_rate: 0.071,
  self_preference_rate: 0.128,
  human_correlation: 0.87,
  total_comparisons: 156,
  gate_status: "pass",
};

const demoProviders: ProviderComparison[] = [
  { name: "Azure OpenAI", quality_stars: 5, latency_ms: 200, cost_per_1k: 0.03, privacy: "cloud" },
  { name: "Ollama (qwen3:8b)", quality_stars: 4, latency_ms: 2500, cost_per_1k: 0, privacy: "local" },
  { name: "Ollama (qwen3:32b)", quality_stars: 5, latency_ms: 12000, cost_per_1k: 0, privacy: "local" },
];

// ── Components ──

function QualityGauge({
  label,
  value,
  size = 100,
}: {
  label: string;
  value: number;
  size?: number;
}) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = circumference * value;
  const color =
    value >= 0.8
      ? "text-emerald-400 stroke-emerald-400"
      : value >= 0.6
        ? "text-amber-400 stroke-amber-400"
        : "text-red-400 stroke-red-400";

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#27272a"
          strokeWidth="6"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={color}
          strokeWidth="6"
          strokeDasharray={`${filled} ${circumference}`}
          strokeLinecap="round"
        />
      </svg>
      <span className={`-mt-16 font-mono text-xl font-bold ${color.split(" ")[0]}`}>
        {(value * 100).toFixed(0)}%
      </span>
      <span className="mt-8 text-xs text-zinc-500">{label}</span>
    </div>
  );
}

// ── Page ──

export default function AnalyticsPage() {
  const [costs, setCosts] = useState<CostsResponse>(demoCosts);
  const [quality, setQuality] = useState<QualityResponse>(demoQuality);
  const [resilience, setResilience] =
    useState<ResilienceResponse>(demoResilience);
  const [period, setPeriod] = useState("7d");
  const [isDemo, setIsDemo] = useState(true);

  useEffect(() => {
    const load = async () => {
      const [c, q, r] = await Promise.all([
        analytics.costs(period),
        analytics.quality(),
        analytics.resilience(),
      ]);
      if (c && c.total_queries > 0) {
        setCosts(c);
        setIsDemo(false);
      }
      if (q) setQuality(q);
      if (r && r.provider_states.length > 0) setResilience(r);
    };
    load();
  }, [period]);

  const maxAgentCost = Math.max(
    ...Object.values(costs.by_agent).map((a) => a.cost),
    0.01
  );

  const maxRoutingPct = Math.max(...demoRouting.map((r) => r.pct), 1);

  const routingColors = [
    "bg-emerald-500/70",
    "bg-blue-500/70",
    "bg-amber-500/70",
    "bg-purple-500/70",
  ];

  const yellowCount = demoDrift.filter((d) => d.severity === "yellow").length;
  const redCount = demoDrift.filter((d) => d.severity === "red").length;
  const overallSeverity = redCount > 0 ? "RED" : yellowCount > 0 ? "YELLOW" : "GREEN";
  const severityAction =
    overallSeverity === "RED"
      ? "Halt deployments."
      : overallSeverity === "YELLOW"
        ? "Monitor."
        : "No action needed.";

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            LLMOps Analytics
          </h1>
          <p className="text-sm text-zinc-500">
            Cost tracking, quality gates, drift monitoring, and provider resilience
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-zinc-700">
            {["24h", "7d", "30d"].map((p) => (
              <Button
                key={p}
                variant="ghost"
                size="sm"
                className={`text-xs ${period === p ? "bg-zinc-800 text-zinc-100" : "text-zinc-500"}`}
                onClick={() => setPeriod(p)}
              >
                {p}
              </Button>
            ))}
          </div>
          {isDemo && (
            <Badge
              variant="outline"
              className="border-amber-500/30 text-amber-400"
            >
              Demo Data
            </Badge>
          )}
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="cost-routing">
        <TabsList className="bg-zinc-900">
          <TabsTrigger value="cost-routing">Cost &amp; Routing</TabsTrigger>
          <TabsTrigger value="quality-drift">Quality &amp; Drift</TabsTrigger>
          <TabsTrigger value="infrastructure">Infrastructure</TabsTrigger>
        </TabsList>

        {/* ════════════════════════════════════════════════════════════════ */}
        {/* Tab 1: Cost & Routing                                          */}
        {/* ════════════════════════════════════════════════════════════════ */}
        <TabsContent value="cost-routing" className="mt-4 space-y-4">
          {/* Cost KPI Cards */}
          <div className="grid grid-cols-4 gap-4">
            {[
              {
                label: "Total Cost",
                value: `EUR ${costs.total_cost.toFixed(2)}`,
                icon: Euro,
                color: "text-emerald-400",
                bg: "bg-emerald-500/10",
              },
              {
                label: "Total Queries",
                value: costs.total_queries.toLocaleString(),
                icon: Hash,
                color: "text-blue-400",
                bg: "bg-blue-500/10",
              },
              {
                label: "Avg Cost/Query",
                value: `EUR ${costs.avg_cost_per_query.toFixed(4)}`,
                icon: TrendingUp,
                color: "text-amber-400",
                bg: "bg-amber-500/10",
              },
              {
                label: "Cache Hit Rate",
                value: `${(costs.cache_hit_rate * 100).toFixed(0)}%`,
                icon: Zap,
                color: "text-purple-400",
                bg: "bg-purple-500/10",
              },
            ].map(({ label, value, icon: Icon, color, bg }) => (
              <Card key={label} className="border-zinc-800 bg-zinc-900">
                <CardContent className="flex items-center justify-between py-4">
                  <div>
                    <p className="text-xs text-zinc-500">{label}</p>
                    <p className={`mt-1 font-mono text-xl font-bold ${color}`}>
                      {value}
                    </p>
                  </div>
                  <div className={`rounded-lg p-2.5 ${bg}`}>
                    <Icon className={`h-5 w-5 ${color}`} />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Cost by Agent */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Cost by Agent
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {Object.entries(costs.by_agent)
                .sort(([, a], [, b]) => b.cost - a.cost)
                .map(([name, data]) => (
                  <div key={name} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-zinc-300">{name}</span>
                      <span className="font-mono text-zinc-400">
                        EUR {data.cost.toFixed(2)} · {data.queries} queries ·{" "}
                        {(data.tokens / 1000).toFixed(0)}K tok
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-zinc-800">
                      <div
                        className="h-2 rounded-full bg-emerald-500/70 transition-all"
                        style={{
                          width: `${(data.cost / maxAgentCost) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
            </CardContent>
          </Card>

          {/* Model Routing Distribution (Phase 7) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Model Routing Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {demoRouting.map((entry, i) => (
                <div key={entry.model} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-300">
                      {entry.model}{" "}
                      <span className="text-zinc-500">— {entry.label}</span>
                    </span>
                    <span className="font-mono text-zinc-400">
                      {entry.pct}% · {entry.queries} queries
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-zinc-800">
                    <div
                      className={`h-2 rounded-full transition-all ${routingColors[i % routingColors.length]}`}
                      style={{
                        width: `${(entry.pct / maxRoutingPct) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
              <Separator className="my-2 bg-zinc-800" />
              <div className="flex items-center gap-2 text-xs text-zinc-400">
                <ArrowDown className="h-3.5 w-3.5 text-emerald-400" />
                <span>
                  Cost savings from routing:{" "}
                  <span className="font-mono font-bold text-emerald-400">83.5%</span>{" "}
                  (EUR 2.28/day vs EUR 14/day all-premium)
                </span>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ════════════════════════════════════════════════════════════════ */}
        {/* Tab 2: Quality & Drift                                         */}
        {/* ════════════════════════════════════════════════════════════════ */}
        <TabsContent value="quality-drift" className="mt-4 space-y-4">
          {/* Quality Gauges */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-zinc-300">
                  RAG Quality Gate
                </CardTitle>
                <Badge
                  variant="outline"
                  className={
                    quality.passes_gate
                      ? "border-emerald-500/30 text-emerald-400"
                      : "border-red-500/30 text-red-400"
                  }
                >
                  {quality.passes_gate ? "PASS" : "FAIL"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-around py-4">
                <QualityGauge
                  label="Precision"
                  value={quality.context_precision}
                />
                <QualityGauge
                  label="Faithfulness"
                  value={quality.faithfulness}
                />
                <QualityGauge
                  label="Relevancy"
                  value={quality.answer_relevancy}
                />
              </div>
              <Separator className="my-3 bg-zinc-800" />
              <p className="text-center text-xs text-zinc-500">
                {quality.dataset_size} eval queries · Last:{" "}
                {quality.last_eval
                  ? new Date(quality.last_eval).toLocaleDateString()
                  : "never"}
              </p>
            </CardContent>
          </Card>

          {/* Drift Monitor (Phase 5) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-zinc-300">
                  Drift Monitor
                </CardTitle>
                <Badge
                  variant="outline"
                  className={
                    overallSeverity === "GREEN"
                      ? "border-emerald-500/30 text-emerald-400"
                      : overallSeverity === "YELLOW"
                        ? "border-amber-500/30 text-amber-400"
                        : "border-red-500/30 text-red-400"
                  }
                >
                  {overallSeverity}
                </Badge>
              </div>
              <p className="text-xs text-zinc-500">
                Current: gpt-5-mini (v2026.03) vs Baseline: gpt-5-mini (v2026.01)
              </p>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800">
                    <TableHead className="text-zinc-500">Metric</TableHead>
                    <TableHead className="text-zinc-500 text-right">Baseline</TableHead>
                    <TableHead className="text-zinc-500 text-right">Current</TableHead>
                    <TableHead className="text-zinc-500 text-right">Delta</TableHead>
                    <TableHead className="text-zinc-500">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {demoDrift.map((d) => {
                    const deltaColor =
                      d.severity === "green"
                        ? "text-emerald-400"
                        : d.severity === "yellow"
                          ? "text-amber-400"
                          : "text-red-400";
                    return (
                      <TableRow key={d.metric} className="border-zinc-800">
                        <TableCell className="text-xs text-zinc-300">
                          <div className="flex items-center gap-1.5">
                            {d.metric}
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-zinc-600 hover:text-zinc-400" />
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-xs border-zinc-700 bg-zinc-900 text-xs text-zinc-300">
                                {d.description}
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-zinc-400">
                          {d.baseline.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-zinc-400">
                          {d.current.toFixed(2)}
                        </TableCell>
                        <TableCell className={`text-right font-mono text-xs ${deltaColor}`}>
                          {d.delta_pct > 0 ? "+" : ""}
                          {d.delta_pct.toFixed(1)}%
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${
                              d.severity === "green"
                                ? "border-emerald-500/30 text-emerald-400"
                                : d.severity === "yellow"
                                  ? "border-amber-500/30 text-amber-400"
                                  : "border-red-500/30 text-red-400"
                            }`}
                          >
                            {d.severity.toUpperCase()}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Separator className="my-3 bg-zinc-800" />
              <p className="text-xs text-zinc-500">
                Drift severity:{" "}
                <span
                  className={
                    overallSeverity === "GREEN"
                      ? "text-emerald-400"
                      : overallSeverity === "YELLOW"
                        ? "text-amber-400"
                        : "text-red-400"
                  }
                >
                  {overallSeverity}
                </span>{" "}
                — {yellowCount > 0 && `${yellowCount} metric${yellowCount > 1 ? "s" : ""} in 2-5% regression. `}
                {redCount > 0 && `${redCount} metric${redCount > 1 ? "s" : ""} in >5% regression. `}
                Action: {severityAction}
              </p>
            </CardContent>
          </Card>

          {/* Judge Bias Scorecard (Phase 5) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-zinc-300">
                  Judge Bias Scorecard
                </CardTitle>
                <Badge
                  variant="outline"
                  className={
                    demoBias.gate_status === "pass"
                      ? "border-emerald-500/30 text-emerald-400"
                      : "border-red-500/30 text-red-400"
                  }
                >
                  {demoBias.gate_status === "pass" ? "PASS" : "HALT"}
                </Badge>
              </div>
              <p className="text-xs text-zinc-500">
                Judge: {demoBias.judge_model} · {demoBias.total_comparisons} comparisons
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Position bias */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 flex items-center gap-1.5">
                  Position bias
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-zinc-600 hover:text-zinc-400" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs border-zinc-700 bg-zinc-900 text-xs text-zinc-300">
                      Rate at which the LLM judge prefers whichever answer appears first, regardless of quality. Measured by swapping answer order and checking if the verdict changes. Below 5% means position has negligible influence.
                    </TooltipContent>
                  </Tooltip>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-emerald-400">
                    {(demoBias.position_bias_rate * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-zinc-600">threshold: &lt;5%</span>
                  <span className="text-emerald-400">&#10003;</span>
                </div>
              </div>
              <Separator className="bg-zinc-800" />

              {/* Verbosity bias */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 flex items-center gap-1.5">
                  Verbosity bias
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-zinc-600 hover:text-zinc-400" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs border-zinc-700 bg-zinc-900 text-xs text-zinc-300">
                      Rate at which the judge prefers longer answers over shorter but equally correct ones. Tested by comparing concise vs verbose versions of the same correct answer. Below 10% is acceptable.
                    </TooltipContent>
                  </Tooltip>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-emerald-400">
                    {(demoBias.verbosity_bias_rate * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-zinc-600">threshold: &lt;10%</span>
                  <span className="text-emerald-400">&#10003;</span>
                </div>
              </div>
              <Separator className="bg-zinc-800" />

              {/* Self-preference */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 flex items-center gap-1.5">
                  Self-preference
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-zinc-600 hover:text-zinc-400" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs border-zinc-700 bg-zinc-900 text-xs text-zinc-300">
                      Rate at which the judge prefers outputs from its own model family (e.g., GPT judging GPT outputs). Same-family judges show 10-15% self-preference inflation. Production scoring uses cross-family evaluation to eliminate this.
                    </TooltipContent>
                  </Tooltip>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-zinc-400">
                    {(demoBias.self_preference_rate * 100).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-zinc-600">(same-family)</span>
                  <span className="text-amber-400">&#9888;</span>
                </div>
              </div>
              <Separator className="bg-zinc-800" />

              {/* Human correlation */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-300 flex items-center gap-1.5">
                  Human correlation
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-zinc-600 hover:text-zinc-400" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs border-zinc-700 bg-zinc-900 text-xs text-zinc-300">
                      Spearman rank correlation between the LLM judge&apos;s scores and human expert scores on a golden evaluation set. Above 0.85 means the judge agrees with humans on which answers are better. Below 0.85 triggers a HALT — automated quality gates cannot be trusted.
                    </TooltipContent>
                  </Tooltip>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-emerald-400">
                    {demoBias.human_correlation.toFixed(2)}
                  </span>
                  <span className="text-[10px] text-zinc-600">threshold: &gt;0.85</span>
                  <span className="text-emerald-400">&#10003;</span>
                </div>
              </div>
              <Separator className="bg-zinc-800" />

              <p className="text-[11px] text-zinc-500">
                Self-preference elevated: judge and target are same OpenAI family.
                Production uses cross-family evaluation.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ════════════════════════════════════════════════════════════════ */}
        {/* Tab 3: Infrastructure                                          */}
        {/* ════════════════════════════════════════════════════════════════ */}
        <TabsContent value="infrastructure" className="mt-4 space-y-4">
          {/* Provider Fallback Chain (Phase 7) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Provider Fallback Chain
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative ml-4">
                {/* Vertical connecting line */}
                <div className="absolute left-5 top-0 bottom-0 w-px border-l-2 border-dashed border-zinc-700" />

                {[
                  {
                    idx: 1,
                    name: "Azure OpenAI",
                    role: "primary",
                    state: resilience.provider_states[0]?.state ?? "closed",
                    calls: resilience.provider_states[0]?.total_calls ?? 1842,
                    failures: resilience.provider_states[0]?.total_failures ?? 3,
                  },
                  {
                    idx: 2,
                    name: "Ollama Local",
                    role: "secondary",
                    state: resilience.provider_states[1]?.state ?? "closed",
                    calls: resilience.provider_states[1]?.total_calls ?? 95,
                    failures: resilience.provider_states[1]?.total_failures ?? 0,
                  },
                  {
                    idx: 3,
                    name: "Azure Fallback",
                    role: "tertiary",
                    state: resilience.provider_states[2]?.state ?? "closed",
                    calls: resilience.provider_states[2]?.total_calls ?? 3,
                    failures: resilience.provider_states[2]?.total_failures ?? 0,
                  },
                  {
                    idx: 4,
                    name: "Semantic Cache",
                    role: "last resort",
                    state: "closed" as const,
                    calls: 12,
                    failures: 0,
                  },
                ].map((provider, i, arr) => {
                  const stateColor =
                    provider.state === "closed"
                      ? "bg-emerald-400"
                      : provider.state === "open"
                        ? "bg-red-400"
                        : "bg-amber-400";
                  const stateBorder =
                    provider.state === "closed"
                      ? "border-emerald-500/30"
                      : provider.state === "open"
                        ? "border-red-500/30"
                        : "border-amber-500/30";
                  const stateLabel =
                    provider.state === "closed"
                      ? "CLOSED"
                      : provider.state === "open"
                        ? "OPEN"
                        : "HALF OPEN";

                  return (
                    <div key={provider.name} className="relative mb-2 last:mb-0">
                      <div className={`ml-10 rounded-lg border bg-zinc-950/50 p-3 ${stateBorder}`}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            {/* Step number */}
                            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-800 font-mono text-xs text-zinc-400">
                              {provider.idx}
                            </span>
                            {/* State dot */}
                            <div className={`h-2.5 w-2.5 rounded-full ${stateColor}`} />
                            <span className="text-sm font-medium text-zinc-200">
                              {provider.name}
                            </span>
                            <Badge
                              variant="outline"
                              className="border-zinc-700 text-[10px] text-zinc-500"
                            >
                              {provider.role}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-4 text-xs text-zinc-400">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                provider.state === "closed"
                                  ? "border-emerald-500/30 text-emerald-400"
                                  : provider.state === "open"
                                    ? "border-red-500/30 text-red-400"
                                    : "border-amber-500/30 text-amber-400"
                              }`}
                            >
                              {stateLabel}
                            </Badge>
                            <span className="font-mono">
                              {provider.calls.toLocaleString()}{" "}
                              {provider.name === "Semantic Cache" ? "hits" : "calls"}
                            </span>
                            {provider.name !== "Semantic Cache" && (
                              <span className="font-mono">
                                {provider.failures} failures
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      {/* Fallback label */}
                      {i < arr.length - 1 && (
                        <div className="ml-14 py-1">
                          <span className="text-[10px] text-zinc-600">
                            {i < arr.length - 2 ? "fallback" : "emergency"}
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <Separator className="my-3 bg-zinc-800" />
              <p className="text-xs text-zinc-500">
                Circuit breaker: 5 failures in 60s → OPEN | Recovery probe: 30s | Failover: &lt;100ms
              </p>
            </CardContent>
          </Card>

          {/* Provider Resilience — Circuit Breakers (existing) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Circuit Breaker States
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-4">
                {resilience.provider_states.map((p) => {
                  const stateColor = {
                    closed: "text-emerald-400 border-emerald-500/30",
                    open: "text-red-400 border-red-500/30",
                    half_open: "text-amber-400 border-amber-500/30",
                  }[p.state];

                  return (
                    <div
                      key={p.name}
                      className={`rounded-lg border bg-zinc-950/50 p-4 ${stateColor.split(" ")[1]}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Database className="h-4 w-4 text-zinc-500" />
                          <span className="text-sm font-medium text-zinc-200">
                            {p.name}
                          </span>
                        </div>
                        <Badge
                          variant="outline"
                          className={`text-xs ${stateColor}`}
                        >
                          {p.state.replace("_", " ").toUpperCase()}
                        </Badge>
                      </div>
                      <div className="mt-3 flex justify-between text-xs text-zinc-500">
                        <span>Calls: {p.total_calls.toLocaleString()}</span>
                        <span>Failures: {p.total_failures}</span>
                        <span>Trips: {p.trips}</span>
                      </div>
                      {/* State machine visualization */}
                      <div className="mt-3 flex items-center justify-center gap-3">
                        {(["closed", "open", "half_open"] as const).map((s) => (
                          <div key={s} className="flex items-center gap-1">
                            <CircleDot
                              className={`h-3 w-3 ${
                                p.state === s
                                  ? s === "closed"
                                    ? "text-emerald-400"
                                    : s === "open"
                                      ? "text-red-400"
                                      : "text-amber-400"
                                  : "text-zinc-700"
                              }`}
                            />
                            <span
                              className={`text-[10px] ${p.state === s ? "text-zinc-300" : "text-zinc-700"}`}
                            >
                              {s.replace("_", " ")}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Cloud vs Local Comparison (Phase 6) */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Cloud vs Local — Provider Comparison
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800">
                    <TableHead className="text-zinc-500">Provider</TableHead>
                    <TableHead className="text-zinc-500">Quality</TableHead>
                    <TableHead className="text-zinc-500 text-right">Latency</TableHead>
                    <TableHead className="text-zinc-500 text-right">Cost/1K</TableHead>
                    <TableHead className="text-zinc-500">Privacy</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {demoProviders.map((prov) => (
                    <TableRow key={prov.name} className="border-zinc-800">
                      <TableCell className="text-xs font-medium text-zinc-300">
                        {prov.name}
                      </TableCell>
                      <TableCell className="text-xs">
                        <span className="text-amber-400">{"★".repeat(prov.quality_stars)}</span>
                        <span className="text-zinc-700">{"★".repeat(5 - prov.quality_stars)}</span>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs text-zinc-400">
                        {prov.latency_ms.toLocaleString()}ms
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs text-zinc-400">
                        {prov.cost_per_1k === 0 ? "EUR 0" : `EUR ${prov.cost_per_1k.toFixed(2)}`}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${
                            prov.privacy === "local"
                              ? "border-emerald-500/30 text-emerald-400"
                              : "border-blue-500/30 text-blue-400"
                          }`}
                        >
                          {prov.privacy === "local" ? "Local" : "Cloud"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Separator className="my-3 bg-zinc-800" />
              <p className="text-xs text-zinc-500">
                Decision: &lt;10K queries/day → cloud. Air-gapped: set{" "}
                <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[10px] text-zinc-400">
                  LLM_PROVIDER=ollama
                </code>
              </p>
            </CardContent>
          </Card>

          {/* Response Quality Gate */}
          <Card className="border-zinc-800 bg-zinc-900">
            <CardContent className="flex items-center gap-3 py-4">
              <div className="rounded-lg bg-emerald-500/10 p-2">
                <ShieldCheck className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-200">
                  Response Quality Gate — Last 24h
                </p>
                <p className="text-xs text-zinc-500">
                  842 responses checked · 0 empty-body failures · 0 invisible-char attacks blocked
                </p>
              </div>
              <div className="ml-auto">
                <Badge
                  variant="outline"
                  className="border-emerald-500/30 text-emerald-400"
                >
                  ALL CLEAR
                </Badge>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
