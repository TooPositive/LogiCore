"use client";

import { useFleetMap, STATUS_COLORS } from "@/lib/fleet-map-context";
import { TruckMap } from "./truck-map";
import { MapControls } from "./map-controls";
import { VehicleDetailPanel } from "./vehicle-detail-panel";
import { VehicleSidebar } from "./vehicle-sidebar";

export function MapShell() {
  const { trucks, anomalyTrucks, statusCounts } = useFleetMap();

  const truckCount = trucks.length;
  const anomalyCount = anomalyTrucks?.size ?? 0;

  return (
    <div className="flex h-full flex-col rounded-lg border border-zinc-800 overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between bg-zinc-900/90 backdrop-blur px-4 py-2 z-10 relative">
        <h3 className="text-sm font-medium text-zinc-300">Fleet Tracking</h3>
        <div className="flex gap-3 text-xs text-zinc-400">
          <span className="font-mono">{truckCount.toLocaleString()} trucks</span>
          {anomalyCount > 0 && (
            <span className="font-mono text-red-400">{anomalyCount} anomalies</span>
          )}
          {(["moving", "idle", "cold_chain", "alert"] as const).map((s) => (
            <span key={s} className="flex items-center gap-1">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: STATUS_COLORS[s] }}
              />
              {s === "cold_chain" ? "Cold" : s.charAt(0).toUpperCase() + s.slice(1)}
              {statusCounts[s] > 0 && (
                <span className="font-mono text-zinc-500">{statusCounts[s]}</span>
              )}
            </span>
          ))}
        </div>
      </div>

      {/* Map area with overlays */}
      <div className="relative flex-1 min-h-0">
        <TruckMap />
        <MapControls />
        <VehicleSidebar />
        <VehicleDetailPanel />
      </div>
    </div>
  );
}
