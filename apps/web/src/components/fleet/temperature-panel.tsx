"use client";

import { Thermometer } from "lucide-react";
import type { TemperatureReading } from "@/lib/types";

function tempColor(temp: number, setpoint: number): string {
  const dev = Math.abs(temp - setpoint);
  if (dev <= 1) return "text-emerald-400";
  if (dev <= 3) return "text-amber-400";
  return "text-red-400";
}

function tempBorder(temp: number, setpoint: number): string {
  const dev = Math.abs(temp - setpoint);
  if (dev <= 1) return "border-zinc-800";
  if (dev <= 3) return "border-amber-500/30";
  return "border-red-500/30";
}

interface TemperaturePanelProps {
  readings: TemperatureReading[];
}

export function TemperaturePanel({ readings }: TemperaturePanelProps) {
  if (readings.length === 0) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2">
        <div className="flex items-center gap-2 text-zinc-600 text-xs">
          <Thermometer className="h-4 w-4" />
          <span>No refrigerated trucks online</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
      <div className="flex items-center gap-3 overflow-x-auto pb-1">
        <div className="flex shrink-0 items-center gap-1.5 pr-2 border-r border-zinc-800">
          <Thermometer className="h-3.5 w-3.5 text-zinc-500" />
          <span className="text-[10px] font-medium text-zinc-400 whitespace-nowrap">
            Cold Chain · {readings.length} trucks
          </span>
        </div>
        {readings.map((r) => {
          const deviation = r.temp_celsius - r.setpoint_celsius;
          return (
            <div
              key={r.truck_id}
              className={`flex shrink-0 items-center gap-2 rounded border bg-zinc-950/50 px-2 py-1.5 ${tempBorder(r.temp_celsius, r.setpoint_celsius)}`}
            >
              <div>
                <span className="font-mono text-[10px] text-zinc-500">
                  {r.truck_id}
                </span>
                <div className={`font-mono text-sm font-bold leading-tight ${tempColor(r.temp_celsius, r.setpoint_celsius)}`}>
                  {r.temp_celsius.toFixed(1)}°C
                </div>
              </div>
              <div className="text-[9px] text-zinc-600 leading-tight">
                <div>set: {r.setpoint_celsius.toFixed(0)}°C</div>
                <div className={Math.abs(deviation) > 1 ? "text-amber-400" : ""}>
                  {deviation > 0 ? "+" : ""}{deviation.toFixed(1)}
                </div>
                <div>{r.cargo_type}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
