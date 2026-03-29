//! Fetch real highway geometries from OSRM (Open Source Routing Machine).
//!
//! On startup, calls the free OSRM demo server for each route to get actual
//! road coordinates. Falls back to hardcoded waypoints if OSRM is unreachable.

use serde::Deserialize;
use tracing::{info, warn};

/// A route defined by name and major city waypoints (OSRM does the actual road routing).
struct RouteSpec {
    name: &'static str,
    /// Waypoints as (lat, lng) — OSRM URL needs (lng, lat) so we flip.
    cities: &'static [(f64, f64)],
}

/// All route specs — just major cities. OSRM fills in the highway geometry.
const ROUTE_SPECS: &[RouteSpec] = &[
    // Western Europe
    RouteSpec { name: "hamburg-zurich", cities: &[
        (53.55, 9.99), (52.37, 9.74), (50.11, 8.68), (49.45, 8.47), (48.78, 9.18), (47.38, 8.54),
    ]},
    RouteSpec { name: "amsterdam-munich", cities: &[
        (52.37, 4.90), (51.44, 5.47), (50.94, 6.96), (50.11, 8.68), (48.14, 11.58),
    ]},
    RouteSpec { name: "rotterdam-vienna", cities: &[
        (51.92, 4.48), (50.94, 6.96), (50.11, 8.68), (49.45, 11.08), (48.21, 16.37),
    ]},
    RouteSpec { name: "berlin-milan", cities: &[
        (52.52, 13.40), (51.34, 12.37), (48.14, 11.58), (47.27, 11.39), (45.46, 9.19),
    ]},
    // Poland
    RouteSpec { name: "warsaw-gdansk", cities: &[
        (52.23, 21.01), (53.01, 18.60), (54.35, 18.65),
    ]},
    RouteSpec { name: "warsaw-berlin", cities: &[
        (52.23, 21.01), (51.76, 19.46), (52.41, 16.93), (52.52, 13.40),
    ]},
    RouteSpec { name: "warsaw-krakow", cities: &[
        (52.23, 21.01), (50.88, 20.03), (50.06, 19.94),
    ]},
    RouteSpec { name: "krakow-vienna", cities: &[
        (50.06, 19.94), (49.82, 19.05), (48.21, 16.37),
    ]},
    RouteSpec { name: "gdansk-wroclaw", cities: &[
        (54.35, 18.65), (53.12, 17.92), (52.41, 16.93), (51.11, 17.03),
    ]},
    RouteSpec { name: "poznan-prague", cities: &[
        (52.41, 16.93), (51.11, 17.03), (50.08, 14.44),
    ]},
    RouteSpec { name: "warsaw-katowice", cities: &[
        (52.23, 21.01), (51.76, 19.46), (50.26, 19.02),
    ]},
    RouteSpec { name: "szczecin-gdansk", cities: &[
        (53.43, 14.53), (54.17, 16.17), (54.35, 18.65),
    ]},
];

#[derive(Deserialize)]
struct OsrmResponse {
    routes: Vec<OsrmRoute>,
}

#[derive(Deserialize)]
struct OsrmRoute {
    geometry: OsrmGeometry,
}

#[derive(Deserialize)]
struct OsrmGeometry {
    coordinates: Vec<Vec<f64>>, // [lng, lat] pairs
}

/// Sample N evenly-spaced points from a coordinate array.
fn sample_points(coords: &[Vec<f64>], target_count: usize) -> Vec<(f64, f64)> {
    if coords.len() <= target_count {
        return coords.iter().map(|c| (c[1], c[0])).collect(); // flip [lng,lat] → (lat,lng)
    }

    let step = (coords.len() - 1) as f64 / (target_count - 1) as f64;
    let mut result = Vec::with_capacity(target_count);

    for i in 0..target_count {
        let idx = (i as f64 * step).round() as usize;
        let idx = idx.min(coords.len() - 1);
        result.push((coords[idx][1], coords[idx][0])); // flip [lng,lat] → (lat,lng)
    }

    result
}

/// Fetch a single route from OSRM.
async fn fetch_route(client: &reqwest::Client, spec: &RouteSpec) -> Option<(String, Vec<(f64, f64)>)> {
    // Build OSRM URL: coordinates as lng,lat;lng,lat;...
    let coords: Vec<String> = spec.cities.iter()
        .map(|(lat, lng)| format!("{},{}", lng, lat))
        .collect();
    let coords_str = coords.join(";");

    let url = format!(
        "http://router.project-osrm.org/route/v1/driving/{}?overview=full&geometries=geojson",
        coords_str
    );

    let resp = client.get(&url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .ok()?;

    let data: OsrmResponse = resp.json().await.ok()?;

    if data.routes.is_empty() {
        return None;
    }

    let geometry = &data.routes[0].geometry.coordinates;
    if geometry.len() < 2 {
        return None;
    }

    // Keep dense waypoints so trucks follow actual roads, not straight lines through cities.
    // OSRM returns 1K-5K points per route; 500 gives sub-km segments across Europe.
    let waypoints = sample_points(geometry, 500);

    Some((spec.name.to_string(), waypoints))
}

/// Fetch all routes from OSRM. Returns Vec of (name, waypoints).
/// Falls back to empty vec on complete failure (caller uses hardcoded fallback).
pub async fn fetch_all_routes() -> Vec<(String, Vec<(f64, f64)>)> {
    info!("Fetching highway geometries from OSRM...");

    let client = reqwest::Client::new();
    let mut routes = Vec::new();
    let mut failed = 0;

    for spec in ROUTE_SPECS {
        match fetch_route(&client, spec).await {
            Some(route) => {
                let count = route.1.len();
                info!("  {} — {} waypoints", route.0, count);
                routes.push(route);
            }
            None => {
                warn!("  {} — OSRM failed, will use fallback", spec.name);
                failed += 1;
            }
        }
    }

    if routes.is_empty() {
        warn!("OSRM unreachable — all routes will use hardcoded fallback");
    } else {
        info!(
            "Fetched {}/{} routes from OSRM (avg {} waypoints each)",
            routes.len(),
            ROUTE_SPECS.len(),
            routes.iter().map(|r| r.1.len()).sum::<usize>() / routes.len().max(1)
        );
        if failed > 0 {
            warn!("{} routes failed — those will use hardcoded fallback", failed);
        }
    }

    routes
}
