"use client";

import {
  createContext,
  useContext,
  useState,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { HeadingCache } from "./heading-calculator";
import type {
  GpsPing,
  TemperatureReading,
  TruckStatus,
  TileMode,
  MapFilter,
} from "./types";

/** Status category indices for PruneCluster. */
export const STATUS_CATEGORY: Record<TruckStatus, number> = {
  alert: 0,
  cold_chain: 1,
  stopped: 2,
  idle: 3,
  moving: 4,
};

export const STATUS_COLORS: Record<TruckStatus, string> = {
  alert: "#ef4444",
  cold_chain: "#38bdf8",
  stopped: "#71717a",
  idle: "#fbbf24",
  moving: "#4ade80",
};

export const STATUS_LABELS: Record<TruckStatus, string> = {
  alert: "Alert",
  cold_chain: "Cold Chain",
  stopped: "Stopped",
  idle: "Idle",
  moving: "Moving",
};

const ALL_STATUSES = new Set<TruckStatus>([
  "alert",
  "cold_chain",
  "stopped",
  "idle",
  "moving",
]);

interface FleetMapContextValue {
  // Data
  trucks: GpsPing[];
  temps: TemperatureReading[];
  anomalyTrucks: Set<string>;
  refrigeratedTrucks: Set<string>;

  // Derived
  truckStatuses: Map<string, TruckStatus>;
  truckHeadings: Map<string, number>;
  truckLookup: Map<string, GpsPing>;
  statusCounts: Record<TruckStatus, number>;

  // Selection
  selectedTruckId: string | null;
  setSelectedTruckId: (id: string | null) => void;

  // Filters
  filters: MapFilter;
  setFilters: React.Dispatch<React.SetStateAction<MapFilter>>;

  // Tile mode
  tileMode: TileMode;
  setTileMode: (mode: TileMode) => void;

  // Layer visibility
  showGeofences: boolean;
  setShowGeofences: (v: boolean) => void;
  showRoutes: boolean;
  setShowRoutes: (v: boolean) => void;

  // Sidebar
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;

  // Map command (imperative from outside the map)
  flyToTruck: (truckId: string) => void;
  flyToRef: React.MutableRefObject<((truckId: string) => void) | null>;
}

const FleetMapContext = createContext<FleetMapContextValue | null>(null);

export function useFleetMap() {
  const ctx = useContext(FleetMapContext);
  if (!ctx) throw new Error("useFleetMap must be used within FleetMapProvider");
  return ctx;
}

interface ProviderProps {
  trucks: GpsPing[];
  temps: TemperatureReading[];
  anomalyTrucks: Set<string>;
  refrigeratedTrucks: Set<string>;
  children: ReactNode;
}

export function FleetMapProvider({
  trucks,
  temps,
  anomalyTrucks,
  refrigeratedTrucks,
  children,
}: ProviderProps) {
  const [selectedTruckId, setSelectedTruckId] = useState<string | null>(null);
  const [filters, setFilters] = useState<MapFilter>({
    statuses: ALL_STATUSES,
    searchQuery: "",
  });
  const [tileMode, setTileMode] = useState<TileMode>("dark");
  const [showGeofences, setShowGeofences] = useState(false);
  const [showRoutes, setShowRoutes] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const headingCacheRef = useRef(new HeadingCache());
  const flyToRef = useRef<((truckId: string) => void) | null>(null);

  // Derive statuses + headings + lookup from truck data
  const { truckStatuses, truckHeadings, truckLookup, statusCounts } = useMemo(() => {
    const statuses = new Map<string, TruckStatus>();
    const lookup = new Map<string, GpsPing>();
    const counts: Record<TruckStatus, number> = {
      alert: 0,
      cold_chain: 0,
      stopped: 0,
      idle: 0,
      moving: 0,
    };

    const cache = headingCacheRef.current;

    for (const truck of trucks) {
      lookup.set(truck.truck_id, truck);
      cache.update(truck.truck_id, truck.lat, truck.lng);

      let status: TruckStatus;
      if (anomalyTrucks.has(truck.truck_id)) {
        status = "alert";
      } else if (refrigeratedTrucks.has(truck.truck_id)) {
        status = "cold_chain";
      } else if (truck.speed_kmh === 0 && !truck.engine_on) {
        status = "stopped";
      } else if (truck.speed_kmh === 0) {
        status = "idle";
      } else {
        status = "moving";
      }

      statuses.set(truck.truck_id, status);
      counts[status]++;
    }

    return {
      truckStatuses: statuses,
      truckHeadings: cache.getAll(),
      truckLookup: lookup,
      statusCounts: counts,
    };
  }, [trucks, anomalyTrucks, refrigeratedTrucks]);

  const flyToTruck = (truckId: string) => {
    setSelectedTruckId(truckId);
    flyToRef.current?.(truckId);
  };

  const value = useMemo<FleetMapContextValue>(
    () => ({
      trucks,
      temps,
      anomalyTrucks,
      refrigeratedTrucks,
      truckStatuses,
      truckHeadings,
      truckLookup,
      statusCounts,
      selectedTruckId,
      setSelectedTruckId,
      filters,
      setFilters,
      tileMode,
      setTileMode,
      showGeofences,
      setShowGeofences,
      showRoutes,
      setShowRoutes,
      sidebarOpen,
      setSidebarOpen,
      flyToTruck,
      flyToRef,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      trucks,
      temps,
      anomalyTrucks,
      refrigeratedTrucks,
      truckStatuses,
      truckHeadings,
      truckLookup,
      statusCounts,
      selectedTruckId,
      filters,
      tileMode,
      showGeofences,
      showRoutes,
      sidebarOpen,
    ]
  );

  return (
    <FleetMapContext.Provider value={value}>{children}</FleetMapContext.Provider>
  );
}
