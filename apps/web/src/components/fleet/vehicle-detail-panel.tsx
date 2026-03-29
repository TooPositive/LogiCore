"use client";

import { X, Navigation, Thermometer, AlertTriangle, Compass } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  useFleetMap,
  STATUS_COLORS,
  STATUS_LABELS,
} from "@/lib/fleet-map-context";

export function VehicleDetailPanel() {
  const {
    selectedTruckId,
    setSelectedTruckId,
    truckLookup,
    truckStatuses,
    truckHeadings,
    temps,
    anomalyTrucks,
    refrigeratedTrucks,
    flyToTruck,
  } = useFleetMap();

  if (!selectedTruckId) return null;

  const truck = truckLookup.get(selectedTruckId);
  if (!truck) return null;

  const status = truckStatuses.get(selectedTruckId) || "moving";
  const heading = truckHeadings.get(selectedTruckId) || 0;
  const tempReading = temps.find((t) => t.truck_id === selectedTruckId);
  const isAlert = anomalyTrucks.has(selectedTruckId);
  const isCold = refrigeratedTrucks.has(selectedTruckId);

  const formatRoute = (name: string) =>
    name
      .split("-")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" → ");

  const headingDirection = (deg: number) => {
    const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    return dirs[Math.round(deg / 45) % 8];
  };

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 z-[1000] animate-in slide-in-from-right duration-300 flex flex-col bg-zinc-950/95 backdrop-blur border-l border-zinc-800 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-bold text-zinc-100">
            {selectedTruckId}
          </span>
          <Badge
            variant="outline"
            className="text-[10px] h-5 px-1.5"
            style={{
              borderColor: STATUS_COLORS[status],
              color: STATUS_COLORS[status],
            }}
          >
            {STATUS_LABELS[status]}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="xs"
          className="h-6 w-6 p-0 text-zinc-500 hover:text-zinc-300"
          onClick={() => setSelectedTruckId(null)}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Alert banner */}
      {isAlert && (
        <div className="mx-3 mt-3 rounded-md border border-red-500/30 bg-red-950/30 px-3 py-2 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
          <span className="text-xs text-red-300">Active anomaly detected</span>
        </div>
      )}

      {/* Position */}
      <div className="px-4 py-3 space-y-2">
        <h4 className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Position
        </h4>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="text-zinc-500">Lat</span>
            <p className="font-mono text-zinc-200">{truck.lat.toFixed(6)}</p>
          </div>
          <div>
            <span className="text-zinc-500">Lng</span>
            <p className="font-mono text-zinc-200">{truck.lng.toFixed(6)}</p>
          </div>
          <div>
            <span className="text-zinc-500">Speed</span>
            <p className="font-mono text-zinc-200">{truck.speed_kmh.toFixed(0)} km/h</p>
          </div>
          <div>
            <span className="text-zinc-500">Heading</span>
            <p className="font-mono text-zinc-200 flex items-center gap-1">
              <Compass className="h-3 w-3" style={{ transform: `rotate(${heading}deg)` }} />
              {heading.toFixed(0)}° {headingDirection(heading)}
            </p>
          </div>
        </div>
      </div>

      <Separator className="bg-zinc-800" />

      {/* Route */}
      <div className="px-4 py-3 space-y-2">
        <h4 className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Route
        </h4>
        <div className="space-y-1 text-xs">
          <div className="flex items-center gap-2">
            <Navigation className="h-3 w-3 text-zinc-500" />
            <span className="text-zinc-200">{formatRoute(truck.route)}</span>
          </div>
          <div className="text-zinc-400">Client: {truck.client}</div>
        </div>
      </div>

      <Separator className="bg-zinc-800" />

      {/* Cold chain (if refrigerated) */}
      {isCold && tempReading && (
        <>
          <div className="px-4 py-3 space-y-2">
            <h4 className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider flex items-center gap-1">
              <Thermometer className="h-3 w-3" /> Cold Chain
            </h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-zinc-500">Temperature</span>
                <p className={`font-mono ${
                  Math.abs(tempReading.temp_celsius - tempReading.setpoint_celsius) > 3
                    ? "text-red-400"
                    : "text-sky-400"
                }`}>
                  {tempReading.temp_celsius.toFixed(1)}°C
                </p>
              </div>
              <div>
                <span className="text-zinc-500">Setpoint</span>
                <p className="font-mono text-zinc-200">{tempReading.setpoint_celsius.toFixed(1)}°C</p>
              </div>
              <div>
                <span className="text-zinc-500">Cargo</span>
                <p className="text-zinc-200">{tempReading.cargo_type}</p>
              </div>
              <div>
                <span className="text-zinc-500">Value</span>
                <p className="font-mono text-zinc-200">
                  {tempReading.cargo_value_eur.toLocaleString("de-DE", {
                    style: "currency",
                    currency: "EUR",
                    maximumFractionDigits: 0,
                  })}
                </p>
              </div>
            </div>
          </div>
          <Separator className="bg-zinc-800" />
        </>
      )}

      {/* Engine status */}
      <div className="px-4 py-3 space-y-2">
        <h4 className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
          Engine
        </h4>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`h-2 w-2 rounded-full ${
              truck.engine_on ? "bg-emerald-400" : "bg-zinc-600"
            }`}
          />
          <span className="text-zinc-200">{truck.engine_on ? "Running" : "Off"}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-auto px-4 py-3 border-t border-zinc-800">
        <Button
          variant="outline"
          size="sm"
          className="w-full border-zinc-700 text-xs text-zinc-300 hover:border-emerald-500/50 hover:text-emerald-400"
          onClick={() => flyToTruck(selectedTruckId)}
        >
          <Navigation className="mr-1.5 h-3 w-3" />
          Center on Map
        </Button>
      </div>
    </div>
  );
}
