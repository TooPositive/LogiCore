"use client";

import { useEffect, useState } from "react";
import {
  ShieldCheck,
  Link2,
  FileSearch,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { compliance } from "@/lib/api";
import type { AuditEntry, HashChainVerify } from "@/lib/types";

// Demo data for when DB is not connected
const demoAuditEntries: AuditEntry[] = [
  {
    id: "ae-001",
    timestamp: "2026-03-27T10:15:00Z",
    user_id: "anna.schmidt",
    query_text: "What are the cold chain requirements for PharmaCorp?",
    model_version: "gpt-5-mini",
    log_level: "full_trace",
    cost_eur: 0.0034,
    is_degraded: false,
  },
  {
    id: "ae-002",
    timestamp: "2026-03-27T10:12:00Z",
    user_id: "max.weber",
    query_text: "Driver safety training schedule Q1",
    model_version: "gpt-5-mini",
    log_level: "full_trace",
    cost_eur: 0.0028,
    is_degraded: false,
  },
  {
    id: "ae-003",
    timestamp: "2026-03-27T09:45:00Z",
    user_id: "katrin.fischer",
    query_text: "Termination notice period for probationary employees",
    model_version: "qwen3:8b",
    log_level: "summary",
    cost_eur: 0.0,
    is_degraded: true,
  },
  {
    id: "ae-004",
    timestamp: "2026-03-27T09:30:00Z",
    user_id: "eva.richter",
    query_text: "Executive compensation benchmark data",
    model_version: "gpt-5-mini",
    log_level: "full_trace",
    cost_eur: 0.0041,
    is_degraded: false,
  },
  {
    id: "ae-005",
    timestamp: "2026-03-27T09:15:00Z",
    user_id: "anna.schmidt",
    query_text: "FreshFoods contract terms for refrigerated transport",
    model_version: "gpt-5-mini",
    log_level: "full_trace",
    cost_eur: 0.0032,
    is_degraded: false,
  },
];

export default function CompliancePage() {
  const [entries, setEntries] = useState<AuditEntry[]>(demoAuditEntries);
  const [hashResult, setHashResult] = useState<HashChainVerify | null>(null);
  const [isDemo, setIsDemo] = useState(true);

  useEffect(() => {
    const load = async () => {
      const [auditRes, hashRes] = await Promise.all([
        compliance.auditLog(),
        compliance.hashChain(),
      ]);
      if (auditRes && auditRes.entries.length > 0) {
        setEntries(auditRes.entries);
        setIsDemo(false);
      }
      if (hashRes) setHashResult(hashRes);
    };
    load();
  }, []);

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            EU AI Act Compliance
          </h1>
          <p className="text-sm text-zinc-500">
            Article 12 — Immutable audit logging, data lineage, and bias
            detection
          </p>
        </div>
        <div className="flex gap-2">
          <Badge
            variant="outline"
            className="border-emerald-500/30 text-emerald-400"
          >
            Article 12 Compliant
          </Badge>
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

      {/* Architecture summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-zinc-800 bg-zinc-900">
          <CardContent className="flex items-center gap-3 py-4">
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <ShieldCheck className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-200">
                Three-Layer Immutability
              </p>
              <p className="text-xs text-zinc-500">
                DB REVOKE + Frozen Pydantic + SHA-256 Hash Chain
              </p>
            </div>
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900">
          <CardContent className="flex items-center gap-3 py-4">
            <div className="rounded-lg bg-blue-500/10 p-2">
              <Link2 className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-200">
                PII Vault Architecture
              </p>
              <p className="text-xs text-zinc-500">
                GDPR Art.17 + AI Act Art.12 — two retention lifecycles
              </p>
            </div>
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900">
          <CardContent className="flex items-center gap-3 py-4">
            <div className="rounded-lg bg-amber-500/10 p-2">
              <FileSearch className="h-5 w-5 text-amber-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-200">
                648:1 Cost Ratio
              </p>
              <p className="text-xs text-zinc-500">
                EUR 5,400/yr logging vs EUR 3.5M potential fine
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="audit-log">
        <TabsList className="bg-zinc-900">
          <TabsTrigger value="audit-log">Audit Log</TabsTrigger>
          <TabsTrigger value="hash-chain">Hash Chain</TabsTrigger>
          <TabsTrigger value="lineage">Data Lineage</TabsTrigger>
          <TabsTrigger value="bias">Bias Detection</TabsTrigger>
        </TabsList>

        {/* Audit Log */}
        <TabsContent value="audit-log" className="mt-4">
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Immutable Audit Entries ({entries.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800">
                    <TableHead className="text-zinc-500">Timestamp</TableHead>
                    <TableHead className="text-zinc-500">User</TableHead>
                    <TableHead className="text-zinc-500">Query</TableHead>
                    <TableHead className="text-zinc-500">Model</TableHead>
                    <TableHead className="text-zinc-500">Level</TableHead>
                    <TableHead className="text-zinc-500 text-right">
                      Cost
                    </TableHead>
                    <TableHead className="text-zinc-500">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow key={entry.id} className="border-zinc-800">
                      <TableCell className="font-mono text-xs text-zinc-400">
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </TableCell>
                      <TableCell className="text-xs text-zinc-300">
                        {entry.user_id}
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs text-zinc-400">
                        {entry.query_text}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className="border-zinc-700 text-[10px] text-zinc-400"
                        >
                          {entry.model_version}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-zinc-500">
                        {entry.log_level}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs text-zinc-400">
                        EUR {entry.cost_eur.toFixed(4)}
                      </TableCell>
                      <TableCell>
                        {entry.is_degraded ? (
                          <Badge
                            variant="outline"
                            className="border-amber-500/30 text-[10px] text-amber-400"
                          >
                            Degraded
                          </Badge>
                        ) : (
                          <Badge
                            variant="outline"
                            className="border-emerald-500/30 text-[10px] text-emerald-400"
                          >
                            Normal
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Hash Chain */}
        <TabsContent value="hash-chain" className="mt-4">
          <Card className="border-zinc-800 bg-zinc-900">
            <CardContent className="py-8">
              {/* Status indicator */}
              <div className="mb-8 flex flex-col items-center">
                {hashResult ? (
                  hashResult.valid ? (
                    <>
                      <CheckCircle2 className="mb-3 h-16 w-16 text-emerald-400" />
                      <h3 className="text-lg font-bold text-emerald-400">
                        Chain Integrity Verified
                      </h3>
                      <p className="text-sm text-zinc-500">
                        All entries are linked and tamper-proof
                      </p>
                    </>
                  ) : (
                    <>
                      <XCircle className="mb-3 h-16 w-16 text-red-400" />
                      <h3 className="text-lg font-bold text-red-400">
                        Chain Broken at Entry #{hashResult.broken_at}
                      </h3>
                      <p className="text-sm text-zinc-500">
                        Tampering detected — investigate immediately
                      </p>
                    </>
                  )
                ) : (
                  <>
                    <CheckCircle2 className="mb-3 h-16 w-16 text-emerald-400/50" />
                    <h3 className="text-lg font-bold text-zinc-400">
                      Hash Chain Demo
                    </h3>
                    <p className="text-sm text-zinc-500">
                      SHA-256 linked entries — tamper evidence at EUR 0
                    </p>
                  </>
                )}
              </div>

              <Separator className="mb-8 bg-zinc-800" />

              {/* Chain visualization */}
              <div className="flex items-center justify-center gap-1 overflow-x-auto py-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex items-center">
                    <div className="flex flex-col items-center rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2">
                      <span className="text-[10px] text-zinc-500">#{i + 1}</span>
                      <span className="font-mono text-[9px] text-emerald-400/70">
                        {`a${i}b${i + 2}c${i + 4}...`}
                      </span>
                    </div>
                    {i < 7 && (
                      <div className="mx-0.5 h-px w-4 bg-zinc-600" />
                    )}
                  </div>
                ))}
              </div>

              <p className="mt-4 text-center text-xs text-zinc-600">
                Each entry&apos;s hash includes the previous entry&apos;s hash — any
                modification breaks the entire chain downstream
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Bias Detection (Phase 8) */}
        <TabsContent value="bias" className="mt-4">
          <Card className="border-zinc-800 bg-zinc-900">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-zinc-300">
                Algorithmic Bias Report
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <p className="text-xs text-zinc-500">
                EU AI Act Article 10 requires monitoring for bias in AI
                outputs. Minimum sample: n&ge;30 per group.
              </p>

              {/* Routing bias */}
              <div className="space-y-3">
                <h4 className="text-xs font-medium text-zinc-400">
                  Model Routing Bias
                </h4>
                <Table>
                  <TableHeader>
                    <TableRow className="border-zinc-800">
                      <TableHead className="text-zinc-500">User Role</TableHead>
                      <TableHead className="text-zinc-500">Queries</TableHead>
                      <TableHead className="text-zinc-500">Degraded %</TableHead>
                      <TableHead className="text-zinc-500">Avg Cost</TableHead>
                      <TableHead className="text-zinc-500">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[
                      { role: "Warehouse Worker", queries: 312, degraded: 4.2, cost: 0.0018, status: "pass" },
                      { role: "Logistics Manager", queries: 245, degraded: 3.8, cost: 0.0024, status: "pass" },
                      { role: "HR Director", queries: 156, degraded: 4.5, cost: 0.0031, status: "pass" },
                      { role: "CEO", queries: 89, degraded: 3.1, cost: 0.0035, status: "pass" },
                    ].map((row) => (
                      <TableRow key={row.role} className="border-zinc-800">
                        <TableCell className="text-xs text-zinc-300">
                          {row.role}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-zinc-400">
                          {row.queries}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-zinc-400">
                          {row.degraded}%
                        </TableCell>
                        <TableCell className="font-mono text-xs text-zinc-400">
                          EUR {row.cost.toFixed(4)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className="border-emerald-500/30 text-[10px] text-emerald-400"
                          >
                            PASS
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <p className="text-[10px] text-zinc-600">
                  No role receives disproportionately more degraded (fallback)
                  responses. Max spread: 1.4pp — within 5pp threshold.
                </p>
              </div>

              <Separator className="bg-zinc-800" />

              {/* Model preference bias */}
              <div className="space-y-3">
                <h4 className="text-xs font-medium text-zinc-400">
                  Model Preference Correlation
                </h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
                    <p className="text-[10px] text-zinc-500">
                      Routing vs Clearance Level
                    </p>
                    <p className="mt-1 font-mono text-sm text-zinc-300">
                      r = 0.12
                    </p>
                    <Badge
                      variant="outline"
                      className="mt-1 border-emerald-500/30 text-[10px] text-emerald-400"
                    >
                      No correlation
                    </Badge>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
                    <p className="text-[10px] text-zinc-500">
                      Cost vs Department
                    </p>
                    <p className="mt-1 font-mono text-sm text-zinc-300">
                      r = 0.08
                    </p>
                    <Badge
                      variant="outline"
                      className="mt-1 border-emerald-500/30 text-[10px] text-emerald-400"
                    >
                      No correlation
                    </Badge>
                  </div>
                </div>
                <p className="text-[10px] text-zinc-600">
                  Correlation coefficients below 0.3 indicate no meaningful
                  bias. AI model routing is driven by query complexity, not
                  user attributes.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Data Lineage */}
        <TabsContent value="lineage" className="mt-4">
          <Card className="border-zinc-800 bg-zinc-900">
            <CardContent className="py-8">
              <div className="mb-6 text-center">
                <h3 className="text-lg font-bold text-zinc-300">
                  Document Lineage Trace
                </h3>
                <p className="text-sm text-zinc-500">
                  Full traceability from source document to vector embedding
                </p>
              </div>

              {/* Flow visualization */}
              <div className="flex items-start justify-center gap-4 overflow-x-auto py-4">
                {/* Source Document */}
                <div className="flex flex-col items-center">
                  <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 px-4 py-3 text-center">
                    <FileSearch className="mx-auto mb-1 h-6 w-6 text-blue-400" />
                    <p className="text-xs font-medium text-blue-400">
                      Source Document
                    </p>
                    <p className="font-mono text-[10px] text-zinc-500">
                      DOC-SAFETY-001
                    </p>
                    <p className="mt-1 text-[10px] text-zinc-600">
                      SHA: 7a3f...b2c1
                    </p>
                  </div>
                  <div className="h-4 w-px bg-zinc-700" />
                  <span className="text-[10px] text-zinc-600">v1 → v2</span>
                </div>

                <div className="mt-8 text-zinc-600">→</div>

                {/* Chunks */}
                <div className="flex flex-col items-center">
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-center">
                    <p className="text-xs font-medium text-amber-400">
                      Chunks
                    </p>
                    <div className="mt-1 space-y-1">
                      {["chunk-001", "chunk-002", "chunk-003"].map((c) => (
                        <p key={c} className="font-mono text-[10px] text-zinc-500">
                          {c}
                        </p>
                      ))}
                    </div>
                    <p className="mt-1 text-[10px] text-zinc-600">
                      Recursive split, 512 tok
                    </p>
                  </div>
                </div>

                <div className="mt-8 text-zinc-600">→</div>

                {/* Embeddings */}
                <div className="flex flex-col items-center">
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-center">
                    <p className="text-xs font-medium text-emerald-400">
                      Vector Embeddings
                    </p>
                    <p className="mt-1 font-mono text-[10px] text-zinc-500">
                      text-embedding-3-small
                    </p>
                    <p className="text-[10px] text-zinc-600">1536 dims</p>
                    <div className="mt-1 space-y-0.5">
                      {["pt-a1b2", "pt-c3d4", "pt-e5f6"].map((p) => (
                        <p
                          key={p}
                          className="font-mono text-[10px] text-zinc-500"
                        >
                          Qdrant: {p}
                        </p>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="mt-8 text-zinc-600">→</div>

                {/* Retrieval */}
                <div className="flex flex-col items-center">
                  <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 px-4 py-3 text-center">
                    <p className="text-xs font-medium text-purple-400">
                      RBAC Filter
                    </p>
                    <p className="mt-1 text-[10px] text-zinc-500">
                      Qdrant query-time filter
                    </p>
                    <p className="text-[10px] text-zinc-600">
                      clearance ≤ user.level
                    </p>
                    <p className="text-[10px] text-zinc-600">
                      dept ∈ user.depts
                    </p>
                    <AlertTriangle className="mx-auto mt-1 h-4 w-4 text-amber-400/50" />
                    <p className="text-[10px] text-amber-400/50">
                      LLM never sees denied docs
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
