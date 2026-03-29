/* eslint-disable @typescript-eslint/no-explicit-any */
declare module "@sintef/prune-cluster" {
  import * as L from "leaflet";

  namespace PruneCluster {
    class Marker {
      position: { lat: number; lng: number };
      data: any;
      category: number;
      weight: number;
      filtered: boolean;
      hashCode: number;

      constructor(
        lat: number,
        lng: number,
        data?: any,
        category?: number,
        weight?: number,
        filtered?: boolean
      );

      Move(lat: number, lng: number): void;
    }

    class Cluster {
      population: number;
      totalWeight: number;
      stats: number[];
      averagePosition: { lat: number; lng: number };
      bounds: L.LatLngBounds;
      lastMarker: Marker;

      static ENABLE_MARKERS_LIST: boolean;

      GetClusterMarkers(): Marker[];
    }

    class PruneCluster {
      Size: number;

      RegisterMarker(marker: Marker): void;
      RemoveMarkers(markers?: Marker[]): void;
      GetMarkers(): Marker[];
      ProcessView(): void;
      GetPopulation(): number;
      ResetClusters(): void;
    }
  }

  class PruneClusterForLeaflet extends L.Layer {
    Cluster: PruneCluster.PruneCluster;

    constructor(size?: number, clusterMargin?: number);

    RegisterMarker(marker: PruneCluster.Marker): void;
    RemoveMarkers(markers?: PruneCluster.Marker[]): void;
    ProcessView(): void;
    FitBounds(): void;
    RedrawIcons(bottomCluster?: PruneCluster.Cluster): void;
    GetMarkers(): PruneCluster.Marker[];

    PrepareLeafletMarker(
      leafletMarker: L.Marker,
      data: any,
      category: number
    ): void;

    BuildLeafletCluster(
      cluster: PruneCluster.Cluster,
      position: L.LatLng
    ): L.Layer;

    BuildLeafletClusterIcon(cluster: PruneCluster.Cluster): L.Icon | L.DivIcon;
  }

  export { PruneCluster, PruneClusterForLeaflet };
}
