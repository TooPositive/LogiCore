"use client";

import { useState } from "react";
import { Moon, Globe, Map, Route, HelpCircle, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  useFleetMap,
  STATUS_COLORS,
  STATUS_LABELS,
} from "@/lib/fleet-map-context";
import type { TruckStatus } from "@/lib/types";

const ALL_STATUSES: TruckStatus[] = ["alert", "cold_chain", "stopped", "idle", "moving"];

export function MapControls() {
  const {
    tileMode,
    setTileMode,
    filters,
    setFilters,
    showGeofences,
    setShowGeofences,
    showRoutes,
    setShowRoutes,
    statusCounts,
  } = useFleetMap();

  const [legendOpen, setLegendOpen] = useState(false);

  const toggleStatus = (status: TruckStatus) => {
    setFilters((prev) => {
      const next = new Set(prev.statuses);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
      }
      return { ...prev, statuses: next };
    });
  };

  return (
    <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
      {/* Tile toggle */}
      <div className="flex gap-1 rounded-lg bg-zinc-900/90 backdrop-blur p-1 border border-zinc-800">
        <Button
          variant="ghost"
          size="xs"
          className={`h-7 w-7 p-0 ${tileMode === "dark" ? "bg-zinc-700 text-emerald-400" : "text-zinc-400"}`}
          onClick={() => setTileMode("dark")}
          title="Dark tiles"
        >
          <Moon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="xs"
          className={`h-7 w-7 p-0 ${tileMode === "satellite" ? "bg-zinc-700 text-emerald-400" : "text-zinc-400"}`}
          onClick={() => setTileMode("satellite")}
          title="Satellite tiles"
        >
          <Globe className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Status filter chips */}
      <div className="flex flex-col gap-1 rounded-lg bg-zinc-900/90 backdrop-blur p-2 border border-zinc-800">
        {ALL_STATUSES.map((status) => {
          const active = filters.statuses.has(status);
          const count = statusCounts[status];
          return (
            <button
              key={status}
              onClick={() => toggleStatus(status)}
              className={`flex items-center gap-2 rounded px-2 py-0.5 text-xs transition-colors ${
                active
                  ? "text-zinc-200"
                  : "text-zinc-600 opacity-50"
              }`}
            >
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ background: active ? STATUS_COLORS[status] : "#52525b" }}
              />
              <span className="flex-1 text-left">{STATUS_LABELS[status]}</span>
              <Badge
                variant="outline"
                className="h-4 px-1 text-[10px] font-mono border-zinc-700 text-zinc-500"
              >
                {count}
              </Badge>
            </button>
          );
        })}
      </div>

      {/* Layer toggles */}
      <div className="flex flex-col gap-1 rounded-lg bg-zinc-900/90 backdrop-blur p-1 border border-zinc-800">
        <Button
          variant="ghost"
          size="xs"
          className={`h-7 justify-start gap-2 px-2 text-xs ${showGeofences ? "text-emerald-400" : "text-zinc-400"}`}
          onClick={() => setShowGeofences(!showGeofences)}
        >
          <Map className="h-3 w-3" />
          Geofences
        </Button>
        <Button
          variant="ghost"
          size="xs"
          className={`h-7 justify-start gap-2 px-2 text-xs ${showRoutes ? "text-emerald-400" : "text-zinc-400"}`}
          onClick={() => setShowRoutes(!showRoutes)}
        >
          <Route className="h-3 w-3" />
          Routes
        </Button>
      </div>

      {/* Legend */}
      <div className="rounded-lg bg-zinc-900/90 backdrop-blur border border-zinc-800">
        <button
          onClick={() => setLegendOpen(!legendOpen)}
          className="flex w-full items-center justify-between px-2 py-1 text-xs text-zinc-400"
        >
          <span className="flex items-center gap-1">
            <HelpCircle className="h-3 w-3" /> Legend
          </span>
          {legendOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
        {legendOpen && (
          <div className="border-t border-zinc-800 px-2 py-1.5 space-y-1">
            {ALL_STATUSES.map((s) => (
              <div key={s} className="flex items-center gap-2 text-[10px] text-zinc-400">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ background: STATUS_COLORS[s] }}
                />
                {STATUS_LABELS[s]}
              </div>
            ))}
            <div className="mt-1 pt-1 border-t border-zinc-800 text-[10px] text-zinc-500">
              Zoom in for directional arrows
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
