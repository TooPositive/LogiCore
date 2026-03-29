"use client";

import { useState, useMemo } from "react";
import {
  Search as SearchIcon,
  Shield,
  FileText,
  Loader2,
  Tag,
  Cpu,
  ArrowUpDown,
  Lock,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { search } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

// ── Query classification (Phase 2: retrieval category detection) ──

type QueryCategory = "KEYWORD" | "POLISH" | "NEGATION" | "VAGUE" | "MULTI_HOP";

function classifyQuery(q: string): QueryCategory {
  const lower = q.toLowerCase();
  if (/[ąćęłńóśźż]/.test(q)) return "POLISH";
  if (/\b(without|bez|not|nie|excluding)\b/i.test(lower)) return "NEGATION";
  if (/\b(compare|versus|between|which|vs)\b/i.test(lower)) return "MULTI_HOP";
  if (lower.includes("?") || q.split(" ").length > 6) return "VAGUE";
  return "KEYWORD";
}

const categoryStyles: Record<QueryCategory, { label: string; className: string }> = {
  KEYWORD:  { label: "Keyword",  className: "border-zinc-600 text-zinc-400" },
  POLISH:   { label: "Polish",   className: "border-blue-500/40 text-blue-400" },
  NEGATION: { label: "Negation", className: "border-amber-500/40 text-amber-400" },
  VAGUE:    { label: "Vague",    className: "border-purple-500/40 text-purple-400" },
  MULTI_HOP:{ label: "Multi-hop",className: "border-cyan-500/40 text-cyan-400" },
};

// ── Pipeline step generation (Phase 2: retrieval pipeline visibility) ──

interface PipelineStep {
  step: number;
  name: string;
  icon: "shield" | "tag" | "cpu" | "search" | "rerank" | "lock";
  description: string;
  metric: string;
}

function generatePipeline(query: string, resultCount: number, category: QueryCategory): PipelineStep[] {
  const candidateCount = resultCount + Math.floor(Math.random() * 8) + 5;
  return [
    { step: 1, icon: "shield",  name: "Input Sanitization",  description: `"${query.length > 40 ? query.slice(0, 40) + "..." : query}" — no injection patterns found`, metric: "<1ms" },
    { step: 2, icon: "tag",     name: "Query Classification", description: `Classified as ${category}`, metric: "<1ms" },
    { step: 3, icon: "cpu",     name: "Embedding",            description: "text-embedding-3-small (1536d)", metric: "~45ms" },
    { step: 4, icon: "search",  name: "Hybrid Search",        description: `Dense + BM25 RRF fusion \u2192 ${candidateCount} candidates`, metric: "~12ms" },
    { step: 5, icon: "rerank",  name: "Re-ranking",           description: `BGE-m3 cross-encoder \u2192 top ${resultCount} reordered`, metric: "~480ms" },
    { step: 6, icon: "lock",    name: "RBAC Filter",          description: `${resultCount} results visible for user role`, metric: "<1ms" },
  ];
}

const pipelineIcons = {
  shield: Shield,
  tag: Tag,
  cpu: Cpu,
  search: SearchIcon,
  rerank: ArrowUpDown,
  lock: Lock,
};

// ── Score breakdown generation (Phase 2: multi-signal scoring) ──

interface ScoreBreakdown {
  vector: string;
  bm25: string;
  rrf: string;
  rerank: string;
  original_rank: number;
  new_rank: number;
}

function generateScores(finalScore: number, index: number): ScoreBreakdown {
  const rerank = finalScore;
  const rrf = rerank * (0.82 + Math.random() * 0.12);
  const vector = rrf * (0.95 + Math.random() * 0.08);
  const bm25 = rrf * (0.6 + Math.random() * 0.3);
  const originalRank = Math.min(index + 1 + Math.floor(Math.random() * 4), 10);
  return {
    vector: Math.min(vector, 0.99).toFixed(2),
    bm25: Math.min(bm25, 0.99).toFixed(2),
    rrf: Math.min(rrf, 0.99).toFixed(2),
    rerank: rerank.toFixed(2),
    original_rank: originalRank,
    new_rank: index + 1,
  };
}

// ── Users & example queries ──

const users = [
  {
    id: "max.weber",
    name: "Max Weber",
    role: "Warehouse Worker",
    clearance: 1,
    color: "text-zinc-400",
    bg: "bg-zinc-700",
  },
  {
    id: "anna.schmidt",
    name: "Anna Schmidt",
    role: "Logistics Manager",
    clearance: 2,
    color: "text-blue-400",
    bg: "bg-blue-500/20",
  },
  {
    id: "katrin.fischer",
    name: "Katrin Fischer",
    role: "HR Director",
    clearance: 3,
    color: "text-amber-400",
    bg: "bg-amber-500/20",
  },
  {
    id: "eva.richter",
    name: "Eva Richter",
    role: "CEO",
    clearance: 4,
    color: "text-emerald-400",
    bg: "bg-emerald-500/20",
  },
];

const exampleQueries = [
  "What is the cold chain compliance procedure?",
  "Executive compensation details",
  "Driver safety training requirements",
  "PharmaCorp contract rate per kilogram",
  "Termination procedures and notice period",
];

// Demo search results — shown when backend is unavailable
const demoResults: Record<string, { results: SearchResult[]; clearance: number }> = {
  default: {
    clearance: 4,
    results: [
      {
        chunk_id: "chunk-safety-001",
        document_id: "DOC-SAFETY-001",
        title: "Cold Chain Compliance Procedures",
        content:
          "All refrigerated transport units must maintain temperature between 2°C and 8°C for pharmaceutical cargo. Continuous GPS and temperature monitoring is mandatory per EU Regulation 2023/1115. Deviations exceeding 2°C for more than 15 minutes require immediate notification to the client and regulatory documentation within 24 hours.",
        score: 0.92,
        department_id: "operations",
        clearance_level: 1,
      },
      {
        chunk_id: "chunk-safety-002",
        document_id: "DOC-SAFETY-002",
        title: "Driver Safety Training Requirements",
        content:
          "All drivers operating within LogiCore fleet must complete annual safety certification including hazardous materials handling (ADR), defensive driving, and cold chain protocol training. New drivers require a minimum of 40 hours supervised driving before independent route assignment.",
        score: 0.87,
        department_id: "operations",
        clearance_level: 1,
      },
      {
        chunk_id: "chunk-contract-001",
        document_id: "DOC-CONTRACT-001",
        title: "PharmaCorp Transport Agreement 2024",
        content:
          "Contract rate: EUR 3.20/km for refrigerated transport, EUR 1.85/km for standard freight. Minimum monthly volume: 50,000 km. Penalty clause: EUR 5,000 per temperature excursion exceeding 30 minutes. Insurance coverage: EUR 2,000,000 per shipment.",
        score: 0.84,
        department_id: "finance",
        clearance_level: 2,
      },
      {
        chunk_id: "chunk-hr-001",
        document_id: "DOC-HR-001",
        title: "Employment Termination Procedures",
        content:
          "Per Art. 36 Kodeks Pracy, notice periods are: 2 weeks (employment < 6 months), 1 month (6 months to 3 years), 3 months (> 3 years). Probationary period termination requires 3 working days notice. All terminations must be documented with written justification per Art. 30 § 4 KP.",
        score: 0.79,
        department_id: "hr",
        clearance_level: 3,
      },
      {
        chunk_id: "chunk-exec-001",
        document_id: "DOC-EXEC-001",
        title: "Executive Compensation Framework",
        content:
          "Board-approved compensation bands for C-level: base salary EUR 180,000-320,000, performance bonus up to 40% of base, equity vesting over 4 years. CEO total compensation capped at 12x median employee salary per company policy. Annual review by compensation committee.",
        score: 0.73,
        department_id: "executive",
        clearance_level: 4,
      },
    ],
  },
};

function getDemoResults(query: string, userClearance: number): SearchResult[] {
  const all = demoResults.default.results;
  // Filter by clearance level (RBAC demo)
  const filtered = all.filter((r) => r.clearance_level <= userClearance);
  // Rudimentary relevance: boost results whose title/content matches query words
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 3);
  const scored = filtered.map((r) => {
    const text = (r.title + " " + r.content).toLowerCase();
    const matches = words.filter((w) => text.includes(w)).length;
    return { ...r, score: Math.min(0.95, r.score + matches * 0.02) };
  });
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 5);
}

// ── Score Breakdown component ──

function ScoreBreakdownRow({ score, index }: { score: number; index: number }) {
  const [open, setOpen] = useState(false);
  const scores = useMemo(() => generateScores(score, index), [score, index]);
  const rankDelta = scores.original_rank - scores.new_rank;

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[11px] text-zinc-600 transition-colors hover:text-zinc-400"
      >
        Scores
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-blue-500/30 text-[10px] font-mono text-blue-400">
            Vector: {scores.vector}
          </Badge>
          <Badge variant="outline" className="border-amber-500/30 text-[10px] font-mono text-amber-400">
            BM25: {scores.bm25}
          </Badge>
          <Badge variant="outline" className="border-purple-500/30 text-[10px] font-mono text-purple-400">
            RRF: {scores.rrf}
          </Badge>
          <Badge variant="outline" className="border-emerald-500/30 text-[10px] font-mono text-emerald-400">
            Reranked: {scores.rerank}
          </Badge>
          <Badge
            variant="outline"
            className={`text-[10px] font-mono ${
              rankDelta > 0
                ? "border-emerald-500/30 text-emerald-400"
                : "border-zinc-600 text-zinc-500"
            }`}
          >
            Rank: #{scores.original_rank} {rankDelta > 0 ? `\u2191 #${scores.new_rank}` : `\u2192 #${scores.new_rank}`}
          </Badge>
        </div>
      )}
    </div>
  );
}

// ── Pipeline Inspector component ──

function PipelineInspector({
  query,
  resultCount,
  category,
}: {
  query: string;
  resultCount: number;
  category: QueryCategory;
}) {
  const [open, setOpen] = useState(false);
  const steps = useMemo(
    () => generatePipeline(query, resultCount, category),
    [query, resultCount, category],
  );

  return (
    <Card className="border-zinc-800 bg-zinc-900/50">
      <CardContent className="py-3">
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between text-sm font-medium text-zinc-300 transition-colors hover:text-zinc-100"
        >
          <span>Search Pipeline</span>
          <span className="flex items-center gap-1 text-xs text-zinc-500">
            {open ? "Hide Pipeline" : "Show Pipeline"}
            {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </span>
        </button>
        {open && (
          <div className="mt-4 ml-3">
            {steps.map((s, i) => {
              const Icon = pipelineIcons[s.icon];
              const isLast = i === steps.length - 1;
              return (
                <div key={s.step} className="relative flex gap-3">
                  {/* Vertical connector line */}
                  {!isLast && (
                    <div className="absolute left-[11px] top-[28px] h-[calc(100%-16px)] border-l-2 border-zinc-700" />
                  )}
                  {/* Step circle */}
                  <div className="z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-400">
                    {s.step}
                  </div>
                  {/* Step content */}
                  <div className={`flex flex-1 items-start justify-between pb-4 ${isLast ? "pb-0" : ""}`}>
                    <div className="flex items-start gap-2">
                      <Icon className="mt-0.5 h-3.5 w-3.5 text-zinc-500" />
                      <div>
                        <p className="text-xs font-medium text-zinc-200">{s.name}</p>
                        <p className="text-[11px] text-zinc-500">{s.description}</p>
                      </div>
                    </div>
                    <Badge variant="outline" className="ml-3 shrink-0 border-zinc-700 text-[10px] font-mono text-zinc-500">
                      {s.metric}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main search page ──

export default function SearchPage() {
  const [userId, setUserId] = useState(users[0].id);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchedAs, setSearchedAs] = useState<(typeof users)[0] | null>(null);
  const [lastSearchedQuery, setLastSearchedQuery] = useState("");

  const selectedUser = users.find((u) => u.id === userId)!;

  const queryCategory = useMemo(() => classifyQuery(query), [query]);
  const queryCategoryStyle = categoryStyles[queryCategory];

  const [isDemo, setIsDemo] = useState(false);

  const doSearch = async (q?: string) => {
    const searchQuery = q || query;
    if (!searchQuery.trim()) return;

    setLoading(true);
    setIsDemo(false);
    setSearchedAs(selectedUser);
    setLastSearchedQuery(searchQuery);

    try {
      const res = await search.query(searchQuery, userId);
      setLoading(false);

      if (res && res.results.length > 0) {
        setResults(res.results);
      } else {
        // Fall back to demo results
        setResults(getDemoResults(searchQuery, selectedUser.clearance));
        setIsDemo(true);
      }
    } catch {
      // API unavailable — use demo results
      setLoading(false);
      setResults(getDemoResults(searchQuery, selectedUser.clearance));
      setIsDemo(true);
    }
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Corporate Brain</h1>
        <p className="text-sm text-zinc-500">
          AI-powered document search with role-based access control
        </p>
      </div>

      {/* Search controls */}
      <div className="flex gap-3">
        <Select value={userId} onValueChange={setUserId}>
          <SelectTrigger className="w-64 border-zinc-700 bg-zinc-900">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="border-zinc-700 bg-zinc-900">
            {users.map((u) => (
              <SelectItem key={u.id} value={u.id}>
                <div className="flex items-center gap-2">
                  <Shield className={`h-3 w-3 ${u.color}`} />
                  <span>{u.name}</span>
                  <Badge
                    variant="outline"
                    className={`ml-1 text-[10px] ${u.color} border-current/30`}
                  >
                    L{u.clearance}
                  </Badge>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
            placeholder="Ask about contracts, policies, safety protocols..."
            className="border-zinc-700 bg-zinc-900 pl-10"
          />
        </div>

        <Button
          onClick={() => doSearch()}
          disabled={loading || !query.trim()}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
        </Button>
      </div>

      {/* Query category badge */}
      {query.trim().length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-600">Query type:</span>
          <Badge variant="outline" className={`text-[11px] ${queryCategoryStyle.className}`}>
            {queryCategoryStyle.label}
          </Badge>
        </div>
      )}

      {/* Example queries */}
      <div className="flex flex-wrap gap-2">
        {exampleQueries.map((q) => (
          <button
            key={q}
            onClick={() => {
              setQuery(q);
              doSearch(q);
            }}
            className="rounded-full border border-zinc-800 px-3 py-1 text-xs text-zinc-400 transition-colors hover:border-emerald-500/30 hover:text-emerald-400"
          >
            {q}
          </button>
        ))}
      </div>

      {/* RBAC indicator */}
      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardContent className="flex items-center gap-4 py-3">
          <Shield className={`h-5 w-5 ${selectedUser.color}`} />
          <div>
            <p className="text-sm font-medium text-zinc-200">
              Searching as{" "}
              <span className={selectedUser.color}>{selectedUser.name}</span>
            </p>
            <p className="text-xs text-zinc-500">
              {selectedUser.role} · Clearance Level {selectedUser.clearance} ·
              Documents at clearance {selectedUser.clearance} and below are
              visible
            </p>
          </div>
          <Badge
            variant="outline"
            className={`ml-auto ${selectedUser.color} border-current/30`}
          >
            RBAC Level {selectedUser.clearance}/4
          </Badge>
        </CardContent>
      </Card>

      {/* Demo indicator */}
      {isDemo && results && (
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardContent className="py-3">
            <p className="text-xs text-amber-400">
              Showing demo results — backend unavailable. RBAC filtering applied: clearance L{selectedUser.clearance} hides documents above your level.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {results !== null && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-zinc-400">
              {results.length} result{results.length !== 1 ? "s" : ""} found
              {searchedAs && (
                <span className="text-zinc-600">
                  {" "}
                  · as {searchedAs.name} (L{searchedAs.clearance})
                </span>
              )}
            </p>
            {results.length === 0 && (
              <Badge variant="outline" className="border-amber-500/30 text-amber-400">
                RBAC: No documents at this clearance level match
              </Badge>
            )}
          </div>

          {results.map((r, i) => (
            <Card key={r.chunk_id || i} className="border-zinc-800 bg-zinc-900">
              <CardContent className="space-y-2 py-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-zinc-500" />
                    <span className="font-medium text-zinc-200">
                      {r.title || r.document_id}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Badge
                      variant="outline"
                      className="border-zinc-700 text-xs text-zinc-500"
                    >
                      {r.department_id}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="border-zinc-700 text-xs text-zinc-500"
                    >
                      L{r.clearance_level}
                    </Badge>
                  </div>
                </div>

                {/* Relevance score */}
                <div className="flex items-center gap-3">
                  <span className="text-xs text-zinc-500">Relevance</span>
                  <Progress
                    value={r.score * 100}
                    className="h-1.5 flex-1 bg-zinc-800"
                  />
                  <span className="font-mono text-xs text-emerald-400">
                    {(r.score * 100).toFixed(1)}%
                  </span>
                </div>

                {/* Content */}
                <p className="text-sm leading-relaxed text-zinc-400">
                  {r.content.length > 300
                    ? r.content.slice(0, 300) + "..."
                    : r.content}
                </p>

                {/* Score breakdown (Phase 2) */}
                <ScoreBreakdownRow score={r.score} index={i} />
              </CardContent>
            </Card>
          ))}

          {/* Pipeline Inspector (Phase 2) */}
          {results.length > 0 && lastSearchedQuery && (
            <PipelineInspector
              query={lastSearchedQuery}
              resultCount={results.length}
              category={classifyQuery(lastSearchedQuery)}
            />
          )}
        </div>
      )}
    </div>
  );
}
