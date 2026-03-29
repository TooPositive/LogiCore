"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Zap, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SummaryCards } from "@/components/fleet/summary-cards";
import { MapShell } from "@/components/fleet/map-shell";
import { AlertFeed } from "@/components/fleet/alert-feed";
import { TemperaturePanel } from "@/components/fleet/temperature-panel";
import { useFleetWebSocket } from "@/lib/use-websocket";
import { FleetMapProvider } from "@/lib/fleet-map-context";
import { sim, fleet, analytics } from "@/lib/api";
import type { GpsPing, TemperatureReading, SimulatorStatus } from "@/lib/types";

export default function FleetDashboard() {
  const [trucks, setTrucks] = useState<GpsPing[]>([]);
  const [temps, setTemps] = useState<TemperatureReading[]>([]);
  const [simStatus, setSimStatus] = useState<SimulatorStatus | null>(null);
  const [alertCount, setAlertCount] = useState(0);
  const [aiCost, setAiCost] = useState(0);
  const [simOnline, setSimOnline] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);
  const { alerts, connected } = useFleetWebSocket();

  // Poll simulator data — 5s interval for 50K trucks
  const pollData = useCallback(async () => {
    const [snapshot, temperatures, status, fleetStatus, costs] =
      await Promise.all([
        sim.snapshot(),
        sim.temperatures(),
        sim.status(),
        fleet.status(),
        analytics.costs("24h"),
      ]);

    if (snapshot) {
      setTrucks(snapshot);
      setSimOnline(true);
    } else {
      setSimOnline(false);
    }
    if (temperatures) setTemps(temperatures);
    if (status) setSimStatus(status);
    if (fleetStatus) setAlertCount(fleetStatus.active_alerts);
    if (costs) setAiCost(costs.total_cost);
  }, []);

  useEffect(() => {
    pollData();
    const interval = setInterval(pollData, 5000);
    return () => clearInterval(interval);
  }, [pollData]);

  // Derive anomaly + refrigerated sets (memoized for 50K)
  const anomalyTrucks = useMemo(
    () => new Set(simStatus?.active_anomalies.map((a) => a.truck_id) ?? []),
    [simStatus]
  );
  const refrigeratedTrucks = useMemo(
    () => new Set(temps.map((t) => t.truck_id)),
    [temps]
  );

  // Scenario triggers — use truck IDs that exist in the fleet
  const trigger = async (name: string, fn: () => Promise<unknown>) => {
    setTriggering(name);
    await fn();
    setTimeout(() => setTriggering(null), 1500);
  };

  const scenarios = [
    {
      label: "Temp Spike (Pharma)",
      fn: () => sim.triggerTempSpike("truck-00003"),
    },
    {
      label: "Speed Anomaly",
      fn: () => sim.triggerSpeedAnomaly("truck-00100"),
    },
    {
      label: "Route Deviation",
      fn: () => sim.triggerRouteDeviation("truck-00200"),
    },
  ];

  // Messages per second estimate
  const msgsPerSec = simOnline ? trucks.length / 5 + temps.length / 5 : 0;

  // Only show first 20 temp readings in the panel (avoid overwhelming UI)
  const displayTemps = temps.slice(0, 20);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            Fleet Dashboard
          </h1>
          <p className="text-xs text-zinc-500">
            Real-time fleet intelligence across European corridors
          </p>
        </div>
        <div className="flex items-center gap-2">
          {scenarios.map((s) => (
            <Button
              key={s.label}
              variant="outline"
              size="sm"
              disabled={!simOnline || triggering !== null}
              className="border-zinc-700 text-xs hover:border-amber-500/50 hover:text-amber-400"
              onClick={() => trigger(s.label, s.fn)}
            >
              <Zap className="mr-1 h-3 w-3" />
              {triggering === s.label ? "Triggered!" : s.label}
            </Button>
          ))}
          <Button
            variant="outline"
            size="sm"
            disabled={!simOnline}
            className="border-zinc-700 text-xs hover:border-zinc-500"
            onClick={() => sim.reset()}
          >
            <RotateCcw className="mr-1 h-3 w-3" />
            Reset
          </Button>
          <Badge
            variant="outline"
            className={
              simOnline
                ? "border-emerald-500/30 text-emerald-400"
                : "border-zinc-700 text-zinc-500"
            }
          >
            {simOnline
              ? `Simulator: ${trucks.length.toLocaleString()} trucks`
              : "Simulator Offline"}
          </Badge>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="px-4 pt-3">
        <SummaryCards
          totalTrucks={trucks.length}
          activeAlerts={alertCount + alerts.filter((a) => !a.resolved).length}
          messagesPerSec={msgsPerSec}
          aiCost={aiCost}
          online={simOnline}
        />
      </div>

      {/* Map + Alert Feed + Temp — fills remaining height */}
      <div className="flex min-h-0 flex-1 gap-4 px-4 py-3">
        {/* Left: Map stacked over temp panel */}
        <FleetMapProvider
          trucks={trucks}
          temps={temps}
          anomalyTrucks={anomalyTrucks}
          refrigeratedTrucks={refrigeratedTrucks}
        >
          <div className="flex flex-1 min-w-0 flex-col gap-3">
            <div className="flex-1 min-h-0">
              <MapShell />
            </div>
            <div className="shrink-0 max-h-36 overflow-auto">
              <TemperaturePanel readings={displayTemps} />
            </div>
          </div>
        </FleetMapProvider>
        {/* Right: Alert feed */}
        <div className="w-80 shrink-0">
          <AlertFeed alerts={alerts} connected={connected} />
        </div>
      </div>
    </div>
  );
}
