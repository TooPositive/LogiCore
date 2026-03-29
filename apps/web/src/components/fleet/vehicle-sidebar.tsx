"use client";

import { useState, useMemo, useCallback } from "react";
import { Truck, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  useFleetMap,
  STATUS_COLORS,
} from "@/lib/fleet-map-context";

export function VehicleSidebar() {
  const {
    trucks,
    truckStatuses,
    filters,
    sidebarOpen,
    setSidebarOpen,
    selectedTruckId,
    flyToTruck,
  } = useFleetMap();

  const [search, setSearch] = useState("");

  // Filter + sort trucks for display
  const filteredTrucks = useMemo(() => {
    const q = search.toLowerCase();
    return trucks
      .filter((t) => {
        const status = truckStatuses.get(t.truck_id);
        if (status && !filters.statuses.has(status)) return false;
        if (q && !t.truck_id.toLowerCase().includes(q) && !t.client.toLowerCase().includes(q)) {
          return false;
        }
        return true;
      })
      .slice(0, 100);
  }, [trucks, truckStatuses, filters, search]);

  const handleSelect = useCallback(
    (truckId: string) => {
      flyToTruck(truckId);
    },
    [flyToTruck]
  );

  // Collapsed state: narrow toggle
  if (!sidebarOpen) {
    return (
      <button
        onClick={() => setSidebarOpen(true)}
        className="absolute left-3 top-3 z-[1000] flex items-center gap-1 rounded-lg bg-zinc-900/90 backdrop-blur border border-zinc-800 px-2 py-2 text-zinc-400 hover:text-zinc-200 transition-colors"
        title="Open vehicle list"
      >
        <Truck className="h-4 w-4" />
        <span className="text-xs font-mono">{trucks.length}</span>
        <ChevronRight className="h-3 w-3" />
      </button>
    );
  }

  return (
    <div className="absolute left-0 top-0 bottom-0 w-72 z-[1000] flex flex-col bg-zinc-950/95 backdrop-blur border-r border-zinc-800 animate-in slide-in-from-left duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Truck className="h-4 w-4 text-zinc-400" />
          <span className="text-xs font-medium text-zinc-300">
            Vehicles ({filteredTrucks.length})
          </span>
        </div>
        <button
          onClick={() => setSidebarOpen(false)}
          className="text-zinc-500 hover:text-zinc-300"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-zinc-800">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" />
          <Input
            placeholder="Search truck ID or client..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-7 pl-7 text-xs bg-zinc-900 border-zinc-800 text-zinc-200 placeholder:text-zinc-600"
          />
        </div>
      </div>

      {/* Truck list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {filteredTrucks.map((truck) => {
          const status = truckStatuses.get(truck.truck_id) || "moving";
          const isSelected = truck.truck_id === selectedTruckId;
          return (
            <button
              key={truck.truck_id}
              onClick={() => handleSelect(truck.truck_id)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-zinc-800/50 transition-colors ${
                isSelected ? "bg-zinc-800/80 border-l-2 border-emerald-400" : "border-l-2 border-transparent"
              }`}
            >
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ background: STATUS_COLORS[status] }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] text-zinc-200 truncate">
                    {truck.truck_id}
                  </span>
                  <span className="font-mono text-[10px] text-zinc-500 ml-2 shrink-0">
                    {truck.speed_kmh.toFixed(0)} km/h
                  </span>
                </div>
                <div className="text-[10px] text-zinc-500 truncate">
                  {truck.client}
                </div>
              </div>
            </button>
          );
        })}
        {filteredTrucks.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-zinc-500">
            No vehicles match filters
          </div>
        )}
      </div>
    </div>
  );
}
