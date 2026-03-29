"use client";

import { useEffect, useRef, useCallback } from "react";
import {
  useFleetMap,
  STATUS_CATEGORY,
  STATUS_COLORS,
} from "@/lib/fleet-map-context";
import { GEOFENCES } from "@/lib/demo-geofences";
import { ROUTE_CORRIDORS } from "@/lib/demo-routes";
import type { TruckStatus } from "@/lib/types";

/* ---------- leaflet / prunecluster type aliases ---------- */
type LType = typeof import("leaflet");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PruneMarker = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PruneClusterLayer = any;

/* ---------- category → colour (indexed by STATUS_CATEGORY) ---------- */
const CATEGORY_COLORS: string[] = [
  STATUS_COLORS.alert,     // 0
  STATUS_COLORS.cold_chain, // 1
  STATUS_COLORS.stopped,   // 2
  STATUS_COLORS.idle,      // 3
  STATUS_COLORS.moving,    // 4
];

/* ================================================================== */
/*  SVG builders                                                       */
/* ================================================================== */

/** Donut cluster icon — arc segments per category with count label. */
function buildDonutSvg(stats: number[], population: number): string {
  const size = population < 50 ? 48 : population < 500 ? 56 : 64;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = size / 2 - 2;
  const innerR = outerR * 0.6;
  const total = stats.reduce((a, b) => a + b, 0);

  if (total === 0) {
    return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:#18181b;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:600">${population}</div>`;
  }

  let paths = "";
  let startAngle = -Math.PI / 2;

  for (let i = 0; i < stats.length; i++) {
    if (stats[i] === 0) continue;
    const fraction = stats[i] / total;
    const endAngle = startAngle + fraction * 2 * Math.PI;

    if (fraction >= 0.9999) {
      // Full circle — single category
      paths += `<circle cx="${cx}" cy="${cy}" r="${(outerR + innerR) / 2}" fill="none" stroke="${CATEGORY_COLORS[i]}" stroke-width="${outerR - innerR}" />`;
    } else {
      const x1o = cx + outerR * Math.cos(startAngle);
      const y1o = cy + outerR * Math.sin(startAngle);
      const x2o = cx + outerR * Math.cos(endAngle);
      const y2o = cy + outerR * Math.sin(endAngle);
      const x1i = cx + innerR * Math.cos(endAngle);
      const y1i = cy + innerR * Math.sin(endAngle);
      const x2i = cx + innerR * Math.cos(startAngle);
      const y2i = cy + innerR * Math.sin(startAngle);
      const largeArc = fraction > 0.5 ? 1 : 0;

      paths += `<path d="M${x1o},${y1o} A${outerR},${outerR} 0 ${largeArc} 1 ${x2o},${y2o} L${x1i},${y1i} A${innerR},${innerR} 0 ${largeArc} 0 ${x2i},${y2i} Z" fill="${CATEGORY_COLORS[i]}" />`;
    }
    startAngle = endAngle;
  }

  // Red alert badge (top-right)
  const alertBadge =
    stats[0] > 0
      ? `<circle cx="${size - 6}" cy="6" r="5" fill="#ef4444" stroke="#18181b" stroke-width="1.5" />`
      : "";

  const label =
    population >= 1000
      ? `${Math.round(population / 1000)}k`
      : `${population}`;

  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5))">
    ${paths}
    <circle cx="${cx}" cy="${cy}" r="${innerR - 1}" fill="#18181b" />
    <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="central" fill="#fff" font-size="${size < 56 ? 11 : 13}" font-weight="600" font-family="ui-monospace,monospace">${label}</text>
    ${alertBadge}
  </svg>`;
}

/** Directional arrow SVG — rotated by heading, with optional alert glow. */
function buildArrowSvg(
  heading: number,
  color: string,
  isAlert: boolean,
): string {
  const glowDef = isAlert
    ? `<defs><filter id="alert-glow"><feGaussianBlur stdDeviation="2" result="blur"/><feFlood flood-color="#ef4444" flood-opacity="0.6" result="color"/><feComposite in="color" in2="blur" operator="in" result="glow"/><feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`
    : "";
  const filterAttr = isAlert ? ' filter="url(#alert-glow)"' : "";

  return `<svg width="24" height="24" viewBox="0 0 24 24" style="transform:rotate(${heading}deg)">
    ${glowDef}
    <polygon points="12,2 20,20 12,16 4,20" fill="${color}" stroke="#18181b" stroke-width="1" stroke-linejoin="round"${filterAttr} />
  </svg>`;
}

/** Simple circle dot for zoomed-out individual markers. */
function buildCircleDot(color: string, isAlert: boolean): string {
  const glow = isAlert ? "box-shadow:0 0 6px 2px rgba(239,68,68,0.6);" : "";
  return `<div style="width:10px;height:10px;border-radius:50%;background:${color};border:1px solid rgba(255,255,255,0.3);${glow}"></div>`;
}

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */

export function TruckMap() {
  const {
    trucks,
    truckStatuses,
    truckHeadings,
    truckLookup,
    filters,
    selectedTruckId,
    setSelectedTruckId,
    tileMode,
    showGeofences,
    showRoutes,
    flyToRef,
  } = useFleetMap();

  /* ----- refs ----- */
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const LRef = useRef<LType | null>(null);

  // PruneCluster
  const clusterRef = useRef<PruneClusterLayer | null>(null);
  const markerCache = useRef<Map<string, PruneMarker>>(new Map());

  // Tile layers
  const darkTilesRef = useRef<L.TileLayer | null>(null);
  const satTilesRef = useRef<L.TileLayer | null>(null);
  const satLabelsRef = useRef<L.TileLayer | null>(null);

  // Overlay layers
  const geofenceLayerRef = useRef<L.LayerGroup | null>(null);
  const routeLayerRef = useRef<L.LayerGroup | null>(null);
  const selectedLayerRef = useRef<L.LayerGroup | null>(null);

  // Zoom level for marker icon switching (arrow vs dot)
  const zoomRef = useRef(6);

  // Stable ref for setSelectedTruckId inside PruneCluster callbacks
  const selectRef = useRef(setSelectedTruckId);
  selectRef.current = setSelectedTruckId;

  /* ================================================================ */
  /*  1. Map initialisation (once)                                     */
  /* ================================================================ */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const init = async () => {
      const L =
        (await import("leaflet")).default || (await import("leaflet"));
      LRef.current = L;

      // PruneCluster relies on window.L — load via script tag
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).L = L;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (!(window as any).PruneClusterForLeaflet) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "/prunecluster.js";
          script.onload = () => resolve();
          script.onerror = () => reject(new Error("PruneCluster failed"));
          document.head.appendChild(script);
        });
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const PCForLeaflet = (window as any).PruneClusterForLeaflet;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const PCMarker = (window as any).PruneCluster?.Marker;

      if (!PCForLeaflet || !PCMarker) {
        console.error("PruneCluster globals not available");
        return;
      }

      /* --- map --- */
      const map = L.map(containerRef.current!, {
        center: [51.0, 14.0],
        zoom: 6,
        preferCanvas: true,
        zoomControl: true,
        attributionControl: false,
      });

      L.control
        .attribution({ position: "bottomright" })
        .addAttribution("CartoDB | Esri")
        .addTo(map);

      /* --- tile layers --- */
      const darkTiles = L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { subdomains: "abcd", maxZoom: 19 },
      );
      const satTiles = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 19 },
      );
      const satLabels = L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
        { subdomains: "abcd", maxZoom: 19, opacity: 0.8 },
      );

      darkTilesRef.current = darkTiles;
      satTilesRef.current = satTiles;
      satLabelsRef.current = satLabels;

      darkTiles.addTo(map); // default

      /* --- PruneCluster --- */
      const cluster = new PCForLeaflet(120, 20);

      // Custom cluster icon (donut)
      cluster.BuildLeafletClusterIcon = function (c: {
        stats: number[];
        population: number;
      }) {
        const size = c.population < 50 ? 48 : c.population < 500 ? 56 : 64;
        return L.divIcon({
          html: buildDonutSvg(c.stats, c.population),
          className: "prune-cluster-icon",
          iconSize: L.point(size, size),
        });
      };

      // Custom individual marker (arrow at zoom >=12, dot otherwise)
      cluster.PrepareLeafletMarker = function (
        leafletMarker: L.Marker,
        data: {
          truck_id: string;
          heading: number;
          status: TruckStatus;
          truck: { client: string; route: string; speed_kmh: number };
        },
        category: number,
      ) {
        const color = CATEGORY_COLORS[category] || CATEGORY_COLORS[4];
        const isAlert = category === 0;
        const zoom = zoomRef.current;

        const icon =
          zoom >= 12
            ? L.divIcon({
                html: buildArrowSvg(data.heading, color, isAlert),
                className: "fleet-marker-arrow",
                iconSize: L.point(24, 24),
                iconAnchor: L.point(12, 12),
              })
            : L.divIcon({
                html: buildCircleDot(color, isAlert),
                className: "fleet-marker-circle",
                iconSize: L.point(10, 10),
                iconAnchor: L.point(5, 5),
              });

        leafletMarker.setIcon(icon);

        // Tooltip
        leafletMarker.bindTooltip(
          `<div style="font-family:ui-monospace,monospace;font-size:11px;line-height:1.4">
            <b>${data.truck_id}</b>
            <span style="color:${color};margin-left:4px">&#9679;</span><br/>
            <span style="color:#a1a1aa">${data.truck.client}</span><br/>
            <span style="color:#a1a1aa">${data.truck.route} &middot; ${data.truck.speed_kmh.toFixed(0)} km/h</span>
          </div>`,
          { direction: "top", className: "truck-tooltip" },
        );

        // Click → select truck
        leafletMarker.off("click").on("click", () => {
          selectRef.current?.(data.truck_id);
        });
      };

      cluster.addTo(map);
      clusterRef.current = cluster;

      // Overlay layer groups (always present, contents toggled)
      geofenceLayerRef.current = L.layerGroup().addTo(map);
      routeLayerRef.current = L.layerGroup().addTo(map);
      selectedLayerRef.current = L.layerGroup().addTo(map);

      // Track zoom for marker icon switching
      map.on("zoomend", () => {
        zoomRef.current = map.getZoom();
        cluster.ProcessView();
      });

      mapRef.current = map;

      // Store PCMarker constructor for the update effect
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (map as any).__PCMarker = PCMarker;
    };

    init();

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
      clusterRef.current = null;
      markerCache.current.clear();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ================================================================ */
  /*  2. Fly-to handler (exposed via context ref)                      */
  /* ================================================================ */
  const flyToHandler = useCallback(
    (truckId: string) => {
      const truck = truckLookup.get(truckId);
      if (!truck || !mapRef.current) return;
      mapRef.current.flyTo(
        [truck.lat, truck.lng],
        Math.max(mapRef.current.getZoom(), 12),
        { duration: 0.8 },
      );
    },
    [truckLookup],
  );

  useEffect(() => {
    flyToRef.current = flyToHandler;
  }, [flyToHandler, flyToRef]);

  /* ================================================================ */
  /*  3. Marker update cycle                                           */
  /* ================================================================ */
  useEffect(() => {
    const cluster = clusterRef.current;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const PCMarker = (mapRef.current as any)?.__PCMarker;
    if (!cluster || !PCMarker) return;

    const currentIds = new Set<string>();

    for (const truck of trucks) {
      currentIds.add(truck.truck_id);

      const status = truckStatuses.get(truck.truck_id) || "moving";
      const category = STATUS_CATEGORY[status];
      const heading = truckHeadings.get(truck.truck_id) || 0;

      // Filter: hidden if status not selected or search query doesn't match
      const statusHidden = !filters.statuses.has(status);
      const q = filters.searchQuery.toLowerCase();
      const searchHidden =
        q.length > 0 &&
        !truck.truck_id.toLowerCase().includes(q) &&
        !truck.client.toLowerCase().includes(q) &&
        !truck.route.toLowerCase().includes(q);
      const filtered = statusHidden || searchHidden;

      const data = {
        truck_id: truck.truck_id,
        heading,
        status,
        truck: {
          client: truck.client,
          route: truck.route,
          speed_kmh: truck.speed_kmh,
        },
      };

      const existing = markerCache.current.get(truck.truck_id);
      if (existing) {
        existing.Move(truck.lat, truck.lng);
        existing.category = category;
        existing.data = data;
        existing.filtered = filtered;
      } else {
        const marker = new PCMarker(truck.lat, truck.lng, data, category);
        marker.filtered = filtered;
        cluster.RegisterMarker(marker);
        markerCache.current.set(truck.truck_id, marker);
      }
    }

    // Remove markers for trucks no longer in the data
    for (const [id, marker] of markerCache.current) {
      if (!currentIds.has(id)) {
        cluster.RemoveMarkers([marker]);
        markerCache.current.delete(id);
      }
    }

    cluster.ProcessView();
  }, [trucks, truckStatuses, truckHeadings, filters]);

  /* ================================================================ */
  /*  4. Tile toggle                                                   */
  /* ================================================================ */
  useEffect(() => {
    const map = mapRef.current;
    if (
      !map ||
      !darkTilesRef.current ||
      !satTilesRef.current ||
      !satLabelsRef.current
    )
      return;

    if (tileMode === "dark") {
      if (map.hasLayer(satTilesRef.current)) map.removeLayer(satTilesRef.current);
      if (map.hasLayer(satLabelsRef.current))
        map.removeLayer(satLabelsRef.current);
      if (!map.hasLayer(darkTilesRef.current))
        darkTilesRef.current.addTo(map);
      darkTilesRef.current.bringToBack();
    } else {
      if (map.hasLayer(darkTilesRef.current))
        map.removeLayer(darkTilesRef.current);
      if (!map.hasLayer(satTilesRef.current)) satTilesRef.current.addTo(map);
      if (!map.hasLayer(satLabelsRef.current))
        satLabelsRef.current.addTo(map);
      satTilesRef.current.bringToBack();
    }
  }, [tileMode]);

  /* ================================================================ */
  /*  5. Geofence layer                                                */
  /* ================================================================ */
  useEffect(() => {
    const L = LRef.current;
    const group = geofenceLayerRef.current;
    if (!L || !group) return;

    group.clearLayers();
    if (!showGeofences) return;

    for (const gf of GEOFENCES) {
      const isCold = gf.warehouseType === "cold_storage";
      const color = isCold ? "#38bdf8" : "#4ade80";

      L.circle([gf.lat, gf.lng], {
        radius: gf.radiusMeters,
        color,
        fillColor: color,
        fillOpacity: 0.06,
        weight: 1.5,
        dashArray: "6 4",
      })
        .bindTooltip(
          `<div style="font-family:ui-monospace,monospace;font-size:11px">
            <b>${gf.label}</b><br/>
            <span style="color:#a1a1aa">${gf.id} &middot; ${gf.country}</span>
          </div>`,
          { direction: "top", className: "truck-tooltip" },
        )
        .addTo(group);
    }
  }, [showGeofences]);

  /* ================================================================ */
  /*  6. Route polylines                                               */
  /* ================================================================ */
  useEffect(() => {
    const L = LRef.current;
    const group = routeLayerRef.current;
    if (!L || !group) return;

    group.clearLayers();

    // Determine selected truck's route name
    const selectedTruck = selectedTruckId
      ? truckLookup.get(selectedTruckId)
      : null;
    const selectedRouteName = selectedTruck?.route;

    // Draw selected truck's route highlighted
    if (selectedRouteName) {
      const corridor = ROUTE_CORRIDORS.find(
        (r) => r.name === selectedRouteName,
      );
      if (corridor) {
        L.polyline(corridor.waypoints, {
          color: "#10b981",
          weight: 3,
          opacity: 0.7,
          dashArray: "10 5",
        }).addTo(group);
      }
    }

    // Draw all routes dim when toggle is on
    if (showRoutes) {
      for (const route of ROUTE_CORRIDORS) {
        if (route.name === selectedRouteName) continue; // already drawn bright
        L.polyline(route.waypoints, {
          color: "#3f3f46",
          weight: 1.5,
          opacity: 0.3,
        }).addTo(group);
      }
    }
  }, [showRoutes, selectedTruckId, truckLookup]);

  /* ================================================================ */
  /*  7. Selected truck overlay (pulsing ring + fly-to)                */
  /* ================================================================ */
  useEffect(() => {
    const L = LRef.current;
    const map = mapRef.current;
    const group = selectedLayerRef.current;
    if (!L || !map || !group) return;

    group.clearLayers();

    if (!selectedTruckId) return;

    const truck = truckLookup.get(selectedTruckId);
    if (!truck) return;

    const status = truckStatuses.get(selectedTruckId) || "moving";
    const color = STATUS_COLORS[status];

    // Pulsing ring around selected truck
    L.circleMarker([truck.lat, truck.lng], {
      radius: 18,
      color,
      weight: 2,
      fillOpacity: 0,
      className: "animate-marker-pulse",
    }).addTo(group);

    // Fly to the selected truck
    map.flyTo(
      [truck.lat, truck.lng],
      Math.max(map.getZoom(), 12),
      { duration: 0.8 },
    );
  }, [selectedTruckId, truckLookup, truckStatuses]);

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */
  return <div ref={containerRef} className="h-full w-full" />;
}
