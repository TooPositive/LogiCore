"use client";

import { Truck, AlertTriangle, Activity, Euro } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface SummaryCardsProps {
  totalTrucks: number;
  activeAlerts: number;
  messagesPerSec: number;
  aiCost: number;
  online: boolean;
}

export function SummaryCards({
  totalTrucks,
  activeAlerts,
  messagesPerSec,
  aiCost,
  online,
}: SummaryCardsProps) {
  const cards = [
    {
      label: "Total Trucks",
      value: totalTrucks,
      format: (v: number) => v.toLocaleString(),
      icon: Truck,
      color: "text-emerald-400",
      bg: "bg-emerald-500/10",
    },
    {
      label: "Active Alerts",
      value: activeAlerts,
      format: (v: number) => v.toString(),
      icon: AlertTriangle,
      color: activeAlerts > 0 ? "text-red-400" : "text-zinc-400",
      bg: activeAlerts > 0 ? "bg-red-500/10" : "bg-zinc-800",
    },
    {
      label: "Messages / sec",
      value: messagesPerSec,
      format: (v: number) =>
        v >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(0),
      icon: Activity,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
    {
      label: "AI Cost (24h)",
      value: aiCost,
      format: (v: number) => `EUR ${v.toFixed(2)}`,
      icon: Euro,
      color: "text-amber-400",
      bg: "bg-amber-500/10",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map(({ label, value, format, icon: Icon, color, bg }) => (
        <Card key={label} className="border-zinc-800 bg-zinc-900">
          <CardContent className="flex items-center justify-between py-4">
            <div>
              <p className="text-xs text-zinc-500">{label}</p>
              <p className={`mt-1 font-mono text-2xl font-bold ${color}`}>
                {online ? format(value) : "---"}
              </p>
            </div>
            <div className={`rounded-lg p-2.5 ${bg}`}>
              <Icon className={`h-5 w-5 ${color}`} />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
