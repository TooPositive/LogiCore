/**
 * Compute bearing (0-360, 0=north, 90=east) between two GPS positions.
 * Uses equirectangular approximation — accurate enough for European latitudes.
 */
export function computeHeading(
  prevLat: number,
  prevLng: number,
  currLat: number,
  currLng: number
): number {
  const dLat = currLat - prevLat;
  const dLng = (currLng - prevLng) * Math.cos(((prevLat + currLat) / 2) * (Math.PI / 180));
  const rad = Math.atan2(dLng, dLat);
  return ((rad * 180) / Math.PI + 360) % 360;
}

/** Minimum movement in degrees (~11 meters) before heading updates. */
const MIN_MOVE = 0.0001;

interface HeadingEntry {
  prevLat: number;
  prevLng: number;
  heading: number;
}

/**
 * Maintains heading per truck, avoiding jitter when movement is tiny.
 */
export class HeadingCache {
  private cache = new Map<string, HeadingEntry>();

  /** Update heading for a truck. Returns current heading (0 if first ping). */
  update(truckId: string, lat: number, lng: number): number {
    const entry = this.cache.get(truckId);
    if (!entry) {
      this.cache.set(truckId, { prevLat: lat, prevLng: lng, heading: 0 });
      return 0;
    }

    const dLat = Math.abs(lat - entry.prevLat);
    const dLng = Math.abs(lng - entry.prevLng);

    if (dLat > MIN_MOVE || dLng > MIN_MOVE) {
      entry.heading = computeHeading(entry.prevLat, entry.prevLng, lat, lng);
      entry.prevLat = lat;
      entry.prevLng = lng;
    }

    return entry.heading;
  }

  get(truckId: string): number {
    return this.cache.get(truckId)?.heading ?? 0;
  }

  getAll(): Map<string, number> {
    const result = new Map<string, number>();
    for (const [id, entry] of this.cache) {
      result.set(id, entry.heading);
    }
    return result;
  }
}
