import type { GeofenceDefinition } from "./types";

/**
 * Warehouse geofences derived from simulator WAREHOUSES + ROUTES endpoint coordinates.
 * Coordinates cross-referenced from fleet.rs route waypoints.
 */
export const GEOFENCES: GeofenceDefinition[] = [
  // Standard warehouses — 3000m radius
  { id: "WH-DE-HH-01", city: "Hamburg",    country: "DE", lat: 53.55,  lng: 9.99,  radiusMeters: 3000, warehouseType: "standard",     label: "Hamburg Warehouse" },
  { id: "WH-DE-FR-02", city: "Frankfurt",  country: "DE", lat: 50.11,  lng: 8.68,  radiusMeters: 3000, warehouseType: "standard",     label: "Frankfurt Warehouse" },
  { id: "WH-DE-MU-03", city: "Munich",     country: "DE", lat: 48.14,  lng: 11.58, radiusMeters: 3000, warehouseType: "standard",     label: "Munich Warehouse" },
  { id: "WH-NL-AM-04", city: "Amsterdam",  country: "NL", lat: 52.37,  lng: 4.90,  radiusMeters: 3000, warehouseType: "standard",     label: "Amsterdam Warehouse" },
  { id: "WH-NL-RT-05", city: "Rotterdam",  country: "NL", lat: 51.92,  lng: 4.48,  radiusMeters: 3000, warehouseType: "standard",     label: "Rotterdam Warehouse" },
  { id: "WH-AT-VI-06", city: "Vienna",     country: "AT", lat: 48.21,  lng: 16.37, radiusMeters: 3000, warehouseType: "standard",     label: "Vienna Warehouse" },
  { id: "WH-IT-MI-07", city: "Milan",      country: "IT", lat: 45.46,  lng: 9.19,  radiusMeters: 3000, warehouseType: "standard",     label: "Milan Warehouse" },
  // Cold storage — 2000m radius (tighter perimeter)
  { id: "CS-DE-HH-01", city: "Hamburg",    country: "DE", lat: 53.55,  lng: 9.99,  radiusMeters: 2000, warehouseType: "cold_storage", label: "Hamburg Cold Storage" },
  { id: "CS-CH-ZH-04", city: "Zurich",     country: "CH", lat: 47.38,  lng: 8.54,  radiusMeters: 2000, warehouseType: "cold_storage", label: "Zurich Cold Storage" },
  { id: "CS-DE-MU-02", city: "Munich",     country: "DE", lat: 48.14,  lng: 11.58, radiusMeters: 2000, warehouseType: "cold_storage", label: "Munich Cold Storage" },
  { id: "CS-NL-RT-03", city: "Rotterdam",  country: "NL", lat: 51.92,  lng: 4.48,  radiusMeters: 2000, warehouseType: "cold_storage", label: "Rotterdam Cold Storage" },
  { id: "CS-AT-VI-05", city: "Vienna",     country: "AT", lat: 48.21,  lng: 16.37, radiusMeters: 2000, warehouseType: "cold_storage", label: "Vienna Cold Storage" },
];
