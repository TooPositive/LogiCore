"use client";

import { useState } from "react";
import { Thermometer, MapPin, Gauge, Radio, Clock, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { FleetAlert, AlertSeverity, AlertType } from "@/lib/types";

const severityColors: Record<AlertSeverity, string> = {
  critical: "bg-red-500/20 text-red-400 border-red-500/30",
  high: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  low: "bg-zinc-700/50 text-zinc-400 border-zinc-600",
};

const typeIcons: Record<AlertType, typeof Thermometer> = {
  temperature_spike: Thermometer,
  temperature_drift: Thermometer,
  gps_deviation: MapPin,
  speed_anomaly: Gauge,
  heartbeat_timeout: Radio,
};

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

interface AlertFeedProps {
  alerts: FleetAlert[];
  connected: boolean;
}

export function AlertFeed({ alerts, connected }: AlertFeedProps) {
  const [resolved, setResolved] = useState<Set<string>>(new Set());

  return (
    <div className="flex h-full flex-col rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <h3 className="text-sm font-medium text-zinc-300">Live Alerts</h3>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-zinc-600"}`}
          />
          <span className="text-xs text-zinc-500">
            {connected ? "Live" : "Disconnected"}
          </span>
        </div>
      </div>

      <ScrollArea className="flex-1 px-2">
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Radio className="mb-2 h-8 w-8 text-zinc-700" />
            <p className="text-sm text-zinc-500">No alerts yet</p>
            <p className="text-xs text-zinc-600">
              Trigger an anomaly to see live alerts
            </p>
          </div>
        ) : (
          <div className="space-y-2 py-2">
            {alerts.map((alert, i) => {
              const Icon = typeIcons[alert.alert_type] || Radio;
              return (
                <div
                  key={alert.alert_id || i}
                  className="animate-alert-in rounded-md border border-zinc-800 bg-zinc-950/50 p-3"
                >
                  <div className="flex items-start gap-2">
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-zinc-200">
                          {alert.truck_id}
                        </span>
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${severityColors[alert.severity]}`}
                        >
                          {alert.severity}
                        </Badge>
                      </div>
                      <p className="mt-0.5 text-xs text-zinc-400 line-clamp-2">
                        {alert.details}
                      </p>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-600">
                        <Clock className="h-3 w-3" />
                        {timeAgo(alert.timestamp)}
                        {alert.cargo_value_eur && (
                          <span className="text-amber-500/70">
                            EUR {alert.cargo_value_eur.toLocaleString()}
                          </span>
                        )}
                        {resolved.has(alert.alert_id) ? (
                          <span className="ml-auto flex items-center gap-1 text-emerald-500">
                            <CheckCircle2 className="h-3 w-3" />
                            Resolved
                          </span>
                        ) : (
                          <button
                            onClick={() =>
                              setResolved((prev) => new Set(prev).add(alert.alert_id))
                            }
                            className="ml-auto text-zinc-500 hover:text-emerald-400 transition-colors"
                          >
                            Resolve
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
