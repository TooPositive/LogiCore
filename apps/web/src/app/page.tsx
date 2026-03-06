import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const services = [
  { name: "API", port: 8080, status: "running", description: "FastAPI backend" },
  { name: "Qdrant", port: 6333, status: "running", description: "Vector database" },
  { name: "PostgreSQL", port: 5432, status: "running", description: "Relational data" },
  { name: "Redis", port: 6379, status: "running", description: "Semantic cache" },
  { name: "Langfuse", port: 3001, status: "running", description: "LLM observability" },
  { name: "Kafka", port: 9092, status: "stopped", description: "Event streaming" },
];

const phases = [
  { number: 1, name: "Corporate Brain", focus: "Hybrid RAG + RBAC", status: "planned" },
  { number: 2, name: "Customs & Finance", focus: "Multi-agent + HITL", status: "planned" },
  { number: 3, name: "Trust Layer", focus: "LLMOps + evaluation", status: "planned" },
  { number: 4, name: "Air-Gapped Vault", focus: "Local inference", status: "planned" },
  { number: 5, name: "Regulatory Shield", focus: "EU AI Act compliance", status: "planned" },
  { number: 6, name: "Fleet Guardian", focus: "Real-time streaming", status: "planned" },
  { number: 7, name: "LLM Firewall", focus: "Security + red teaming", status: "planned" },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl px-6 py-12">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-bold tracking-tight">
            Logi<span className="text-emerald-400">Core</span>
          </h1>
          <p className="mt-2 text-lg text-zinc-400">
            Enterprise AI Operating System for Logistics & Supply Chain
          </p>
          <div className="mt-4 flex gap-2">
            <Badge variant="outline" className="border-emerald-500/30 text-emerald-400">
              v0.1.0
            </Badge>
            <Badge variant="outline" className="border-zinc-700 text-zinc-400">
              Phase 0 — Skeleton
            </Badge>
          </div>
        </div>

        {/* Services Grid */}
        <section className="mb-12">
          <h2 className="mb-4 text-xl font-semibold text-zinc-300">Infrastructure</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {services.map((service) => (
              <Card key={service.name} className="border-zinc-800 bg-zinc-900">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base text-zinc-100">{service.name}</CardTitle>
                    <Badge
                      variant={service.status === "running" ? "default" : "secondary"}
                      className={
                        service.status === "running"
                          ? "bg-emerald-500/10 text-emerald-400"
                          : "bg-zinc-800 text-zinc-500"
                      }
                    >
                      {service.status}
                    </Badge>
                  </div>
                  <CardDescription className="text-zinc-500">
                    :{service.port}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-zinc-400">{service.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* Phases */}
        <section>
          <h2 className="mb-4 text-xl font-semibold text-zinc-300">Build Phases</h2>
          <div className="space-y-3">
            {phases.map((phase) => (
              <Card key={phase.number} className="border-zinc-800 bg-zinc-900">
                <CardContent className="flex items-center justify-between py-4">
                  <div className="flex items-center gap-4">
                    <span className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-800 text-sm font-mono font-bold text-zinc-400">
                      {phase.number}
                    </span>
                    <div>
                      <p className="font-medium text-zinc-100">{phase.name}</p>
                      <p className="text-sm text-zinc-500">{phase.focus}</p>
                    </div>
                  </div>
                  <Badge variant="outline" className="border-zinc-700 text-zinc-500">
                    {phase.status}
                  </Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
