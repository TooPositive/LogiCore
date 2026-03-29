declare module "prunecluster" {
  import * as L from "leaflet";

  export class PruneCluster {
    constructor(size?: number, clusterMargin?: number);
    RegisterMarker(marker: PruneCluster.Marker): void;
    RemoveMarkers(markers: PruneCluster.Marker[]): void;
    ProcessView(): void;
    RedrawIcons(): void;
    Cluster: { Size: number };
  }

  export namespace PruneCluster {
    class Marker {
      constructor(lat: number, lng: number, options?: Record<string, unknown>);
      Move(lat: number, lng: number): void;
      category: number;
      weight: number;
      data: Record<string, unknown>;
      position: { lat: number; lng: number };
      filtered: boolean;
    }
  }

  export class PruneClusterForLeaflet extends L.Layer {
    constructor(size?: number, clusterMargin?: number);
    RegisterMarker(marker: PruneCluster.Marker): void;
    RemoveMarkers(markers: PruneCluster.Marker[]): void;
    ProcessView(): void;
    RedrawIcons(): void;
    BuildLeafletClusterIcon: (
      cluster: {
        population: number;
        stats: number[];
        totalWeight: number;
        bounds: L.LatLngBounds;
        averagePosition: { lat: number; lng: number };
      },
    ) => L.Icon | L.DivIcon;
    BuildLeafletMarker: (
      marker: PruneCluster.Marker,
      position: L.LatLng,
    ) => L.Marker;
    PrepareLeafletMarker: (
      leafletMarker: L.Marker,
      data: Record<string, unknown>,
      category: number,
    ) => void;
    Cluster: { Size: number };
  }
}
