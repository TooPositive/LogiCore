//! Fleet data generators — trucks, GPS pings, temperature readings.
//!
//! Each truck follows a real European route defined as waypoints (lat/lng).
//! GPS pings interpolate between waypoints at realistic speeds.
//! Temperature readings hover around set point with random noise.

use chrono::Utc;
use rand::Rng;
use serde::Serialize;
use tokio::sync::RwLock;

/// Real European highway waypoints — dense, following actual A-roads / E-roads.
pub const ROUTES: &[(&str, &[(f64, f64)])] = &[
    // === WESTERN EUROPE ===
    ("hamburg-zurich", &[  // A7 → A5 → A81 → A1
        (53.55, 9.99), (53.23, 9.93), (52.72, 9.84), (52.37, 9.74),  // Hamburg → Hannover
        (52.02, 9.65), (51.72, 9.38), (51.43, 9.24), (51.13, 8.76),  // Hannover → Kassel
        (50.72, 8.32), (50.42, 8.23), (50.11, 8.68),                  // Kassel → Frankfurt
        (49.74, 8.62), (49.48, 8.47), (49.23, 8.68),                  // Frankfurt → Mannheim → Karlsruhe
        (48.89, 9.10), (48.78, 9.18), (48.52, 9.05),                  // Stuttgart area
        (48.20, 8.81), (47.80, 8.68), (47.55, 8.56), (47.38, 8.54),  // → Zurich
    ]),
    ("amsterdam-munich", &[  // A2 → A3 → A9
        (52.37, 4.90), (52.18, 5.18), (52.08, 5.48), (51.68, 5.50),  // Amsterdam → Utrecht → Eindhoven
        (51.44, 5.47), (51.22, 5.78), (51.00, 6.16), (50.94, 6.96),  // Eindhoven → Cologne
        (50.77, 7.19), (50.58, 7.52), (50.35, 7.86), (50.11, 8.68),  // Cologne → Frankfurt
        (49.87, 8.94), (49.62, 9.32), (49.44, 9.82), (49.12, 10.62), // Frankfurt → Nuremberg
        (49.01, 12.10), (48.63, 11.92), (48.36, 11.78), (48.14, 11.58), // → Munich
    ]),
    ("rotterdam-vienna", &[  // A12 → A3 → A3 → A1(AT)
        (51.92, 4.48), (51.83, 4.82), (51.62, 5.34), (51.44, 5.47),  // Rotterdam → Eindhoven
        (51.22, 5.78), (51.00, 6.16), (50.94, 6.96), (50.72, 7.41),  // → Cologne → Bonn
        (50.35, 7.86), (50.11, 8.68), (49.88, 9.19), (49.58, 10.12), // → Frankfurt → Würzburg
        (49.45, 11.08), (49.12, 11.62), (48.76, 12.35), (48.56, 13.12), // Nuremberg → Passau
        (48.31, 14.29), (48.25, 15.42), (48.21, 16.37),               // Linz → Vienna
    ]),
    ("berlin-milan", &[  // A9 → A93 → A12(AT) → A22(IT)
        (52.52, 13.40), (52.28, 13.08), (51.84, 12.64), (51.34, 12.37), // Berlin → Leipzig
        (50.92, 12.08), (50.48, 11.84), (50.08, 11.78), (49.68, 11.98), // → Hof → Bayreuth
        (49.32, 12.06), (49.01, 12.10), (48.63, 11.92), (48.14, 11.58), // → Regensburg → Munich
        (47.86, 11.48), (47.52, 11.40), (47.27, 11.39), (47.05, 11.24), // → Innsbruck → Brenner
        (46.72, 11.16), (46.37, 11.12), (46.07, 11.12), (45.78, 10.38), // → Trento → Verona
        (45.62, 9.68), (45.46, 9.19),                                    // → Milan
    ]),
    // === POLISH CORRIDORS (following actual A/S roads) ===
    ("warsaw-gdansk", &[  // S7 highway
        (52.23, 21.01), (52.36, 20.85), (52.52, 20.67), (52.68, 20.48), // Warsaw north
        (52.88, 20.23), (53.05, 19.98), (53.18, 19.67), (53.32, 19.38), // Płońsk area
        (53.48, 19.12), (53.65, 18.88), (53.82, 18.72), (54.02, 18.66), // → Tczew
        (54.18, 18.63), (54.35, 18.65),                                   // → Gdańsk
    ]),
    ("warsaw-berlin", &[  // A2 highway (E30)
        (52.23, 21.01), (52.21, 20.62), (52.18, 20.22), (52.14, 19.82), // Warsaw → Łowicz
        (52.08, 19.42), (51.98, 19.02), (51.88, 18.62), (51.84, 18.22), // → Łódź bypass
        (51.88, 17.82), (51.92, 17.42), (51.96, 17.02), (52.00, 16.62), // → Poznań approach
        (52.08, 16.22), (52.16, 15.82), (52.24, 15.42), (52.30, 15.02), // → Świecko
        (52.34, 14.62), (52.38, 14.22), (52.42, 13.82), (52.52, 13.40), // Frankfurt(Oder) → Berlin
    ]),
    ("warsaw-krakow", &[  // A1/S7 → E77
        (52.23, 21.01), (52.08, 20.88), (51.88, 20.72), (51.68, 20.56), // Warsaw south
        (51.48, 20.42), (51.28, 20.28), (51.08, 20.15), (50.88, 20.03), // → Radom → Kielce
        (50.68, 19.95), (50.52, 19.93), (50.38, 19.94), (50.22, 19.94), // → Miechów
        (50.06, 19.94),                                                    // → Kraków
    ]),
    ("krakow-vienna", &[  // A4 → E77 → D1(SK) → E65
        (50.06, 19.94), (49.98, 19.72), (49.88, 19.48), (49.82, 19.18), // Kraków → Bielsko-Biała
        (49.72, 18.88), (49.58, 18.72), (49.38, 18.62), (49.21, 18.74), // → Žilina (SK)
        (49.02, 18.38), (48.88, 17.98), (48.72, 17.58), (48.58, 17.18), // → Bratislava approach
        (48.42, 16.88), (48.30, 16.62), (48.21, 16.37),                  // → Vienna
    ]),
    ("gdansk-wroclaw", &[  // S6 → A1 → S5 → A2 → S5 → S8
        (54.35, 18.65), (54.18, 18.42), (53.98, 18.22), (53.78, 18.08), // Gdańsk south
        (53.58, 17.94), (53.38, 17.82), (53.12, 17.62), (52.88, 17.42), // → Bydgoszcz
        (52.62, 17.22), (52.41, 16.93), (52.18, 16.82), (51.92, 16.88), // → Poznań → south
        (51.68, 16.94), (51.42, 17.00), (51.22, 17.02), (51.11, 17.03), // → Wrocław
    ]),
    ("poznan-prague", &[  // A2 → S5 → A4 → E67 → D11
        (52.41, 16.93), (52.22, 16.86), (51.98, 16.92), (51.68, 16.98), // Poznań → Leszno
        (51.42, 17.02), (51.22, 17.03), (51.11, 17.03), (50.92, 16.82), // → Wrocław
        (50.78, 16.58), (50.62, 16.32), (50.48, 16.08), (50.38, 15.78), // → Kłodzko → border
        (50.28, 15.52), (50.18, 15.22), (50.08, 14.88), (50.08, 14.44), // → Prague
    ]),
    ("warsaw-katowice", &[  // A1 → E75/A1
        (52.23, 21.01), (52.08, 20.82), (51.88, 20.42), (51.76, 19.82), // Warsaw → Łódź
        (51.76, 19.46), (51.72, 19.18), (51.62, 19.12), (51.42, 19.14), // Łódź → south
        (51.22, 19.12), (51.02, 19.08), (50.82, 19.12), (50.62, 19.08), // → Częstochowa
        (50.42, 19.04), (50.26, 19.02),                                   // → Katowice
    ]),
    ("szczecin-gdansk", &[  // S6 / S3 — Baltic coast
        (53.43, 14.53), (53.52, 14.92), (53.68, 15.32), (53.78, 15.62), // Szczecin → Stargard
        (53.88, 15.92), (54.02, 16.18), (54.12, 16.48), (54.18, 16.82), // → Koszalin
        (54.22, 17.18), (54.28, 17.52), (54.32, 17.88), (54.34, 18.22), // → Słupsk → Lębork
        (54.35, 18.65),                                                    // → Gdańsk
    ]),
];

#[derive(Debug, Clone, Serialize)]
pub struct CargoType {
    pub cargo_type: &'static str,
    pub temp_setpoint: Option<f64>,
    pub value_eur: u32,
    pub perishable: bool,
}

pub const CARGO_TYPES: &[CargoType] = &[
    CargoType { cargo_type: "pharmaceutical",   temp_setpoint: Some(3.0),   value_eur: 180_000, perishable: true },
    CargoType { cargo_type: "frozen_food",       temp_setpoint: Some(-18.0), value_eur: 45_000,  perishable: true },
    CargoType { cargo_type: "dairy",             temp_setpoint: Some(4.0),   value_eur: 22_000,  perishable: true },
    CargoType { cargo_type: "electronics",       temp_setpoint: None,        value_eur: 95_000,  perishable: false },
    CargoType { cargo_type: "automotive_parts",  temp_setpoint: None,        value_eur: 67_000,  perishable: false },
    CargoType { cargo_type: "chemicals",         temp_setpoint: Some(15.0),  value_eur: 120_000, perishable: false },
    CargoType { cargo_type: "textiles",          temp_setpoint: None,        value_eur: 18_000,  perishable: false },
];

pub const CLIENTS: &[&str] = &[
    "PharmaCorp AG", "FreshFoods GmbH", "ElectroParts BV",
    "AlpenDairy", "ChemTrans SE", "AutoLogistik",
    "NordFisch", "MediSupply", "TechHaus", "SwissAgri",
];

#[derive(Debug, Clone, Serialize)]
pub struct GpsPing {
    pub truck_id: String,
    pub lat: f64,
    pub lng: f64,
    pub speed_kmh: f64,
    pub engine_on: bool,
    pub route: String,
    pub client: String,
    pub timestamp: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TemperatureReading {
    pub truck_id: String,
    pub sensor_id: String,
    pub temp_celsius: f64,
    pub setpoint_celsius: f64,
    pub cargo_type: String,
    pub cargo_value_eur: u32,
    pub timestamp: String,
}

#[derive(Debug, Clone)]
pub struct Truck {
    pub truck_id: String,
    pub route_name: String,
    pub route_waypoints: Vec<(f64, f64)>,
    pub cargo: CargoType,
    pub client: String,
    pub refrigerated: bool,
    pub current_waypoint_idx: usize,
    pub progress_between: f64,
    pub speed_kmh: f64,
    pub engine_on: bool,
    pub anomaly_active: Option<String>,
    pub forward: bool,
    /// Per-segment step size — adapts to waypoint density so all routes traverse in similar time.
    pub tick_step: f64,
}

impl Truck {
    fn current_position(&self) -> (f64, f64) {
        let len = self.route_waypoints.len();
        if self.current_waypoint_idx >= len - 1 {
            return self.route_waypoints[len - 1];
        }

        let a = self.route_waypoints[self.current_waypoint_idx];
        let b = self.route_waypoints[self.current_waypoint_idx + 1];
        let t = self.progress_between;
        (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t)
    }

    /// Advance truck position, return GPS ping.
    pub fn tick(&mut self) -> GpsPing {
        let mut rng = rand::thread_rng();

        // Move forward — step adapts to waypoint density
        let jitter = self.tick_step * 0.25;
        self.progress_between += self.tick_step + rng.gen_range(-jitter..jitter);
        if self.progress_between >= 1.0 {
            self.progress_between = 0.0;
            if self.forward {
                self.current_waypoint_idx += 1;
                if self.current_waypoint_idx >= self.route_waypoints.len() - 1 {
                    self.forward = false;
                    self.current_waypoint_idx = self.route_waypoints.len() - 2;
                }
            } else {
                if self.current_waypoint_idx == 0 {
                    self.forward = true;
                } else {
                    self.current_waypoint_idx -= 1;
                }
            }
        }

        // Speed variation
        self.speed_kmh = (80.0_f64 + rng.gen_range(-16.0..16.0)).max(0.0);

        let (lat, lng) = self.current_position();
        GpsPing {
            truck_id: self.truck_id.clone(),
            lat: (lat * 1_000_000.0).round() / 1_000_000.0,
            lng: (lng * 1_000_000.0).round() / 1_000_000.0,
            speed_kmh: (self.speed_kmh * 10.0).round() / 10.0,
            engine_on: self.engine_on,
            route: self.route_name.clone(),
            client: self.client.clone(),
            timestamp: Utc::now().to_rfc3339(),
        }
    }

    /// Generate temperature reading for refrigerated trucks.
    pub fn temperature_reading(&self) -> Option<TemperatureReading> {
        if !self.refrigerated {
            return None;
        }
        let setpoint = self.cargo.temp_setpoint?;

        let mut rng = rand::thread_rng();
        let mut temp = setpoint + rng.gen_range(-0.6..0.6);

        // If anomaly active, spike temperature
        if self.anomaly_active.as_deref() == Some("temperature-spike") {
            temp = setpoint + rng.gen_range(8.0..15.0);
        }

        Some(TemperatureReading {
            truck_id: self.truck_id.clone(),
            sensor_id: format!("{}-temp-01", self.truck_id),
            temp_celsius: (temp * 10.0).round() / 10.0,
            setpoint_celsius: setpoint,
            cargo_type: self.cargo.cargo_type.to_string(),
            cargo_value_eur: self.cargo.value_eur,
            timestamp: Utc::now().to_rfc3339(),
        })
    }
}

/// Sharded fleet — distributes trucks across N independent locks.
///
/// At 50 trucks / 4 shards = ~12 trucks per lock.
/// At 50K trucks / 64 shards = ~780 trucks per lock.
/// Scenario triggers lock ONE shard. Background loops process shards
/// sequentially so HTTP handlers can interleave between them.
pub struct ShardedFleet {
    shards: Vec<RwLock<Vec<Truck>>>,
    shard_count: usize,
    total_trucks: usize,
    refrigerated_count: usize,
}

impl ShardedFleet {
    /// Build a sharded fleet. `shard_count = 0` means auto (truck_count / 16, min 1).
    /// If `osrm_routes` is non-empty, uses those instead of hardcoded ROUTES.
    pub fn new(
        truck_count: usize,
        refrigerated_count: usize,
        shard_count: usize,
        osrm_routes: Vec<(String, Vec<(f64, f64)>)>,
    ) -> Self {
        let shard_count = if shard_count == 0 {
            (truck_count / 16).max(1)
        } else {
            shard_count
        };

        let trucks = create_trucks(truck_count, refrigerated_count, &osrm_routes);
        let mut buckets: Vec<Vec<Truck>> = (0..shard_count).map(|_| Vec::new()).collect();
        for (i, truck) in trucks.into_iter().enumerate() {
            buckets[i % shard_count].push(truck);
        }

        Self {
            shards: buckets.into_iter().map(RwLock::new).collect(),
            shard_count,
            total_trucks: truck_count,
            refrigerated_count,
        }
    }

    pub fn total_trucks(&self) -> usize {
        self.total_trucks
    }

    pub fn refrigerated_count(&self) -> usize {
        self.refrigerated_count
    }

    pub fn shard_count(&self) -> usize {
        self.shard_count
    }

    /// Resolve truck-NNNN to its shard index.
    fn shard_for_id(&self, truck_id: &str) -> Option<usize> {
        let num: usize = truck_id.strip_prefix("truck-")?.parse().ok()?;
        Some(num % self.shard_count)
    }

    /// Tick all trucks — processes shards sequentially so each lock is held briefly.
    pub async fn tick_all(&self) {
        for shard in &self.shards {
            let mut trucks = shard.write().await;
            for truck in trucks.iter_mut() {
                truck.tick();
            }
        }
    }

    /// GPS snapshot of all trucks (ticks them forward).
    pub async fn snapshot_all(&self) -> Vec<GpsPing> {
        let mut pings = Vec::with_capacity(self.total_trucks);
        for shard in &self.shards {
            let mut trucks = shard.write().await;
            pings.extend(trucks.iter_mut().map(|t| t.tick()));
        }
        pings
    }

    /// Temperature readings for all refrigerated trucks.
    pub async fn temperatures_all(&self) -> Vec<TemperatureReading> {
        let mut readings = Vec::with_capacity(self.refrigerated_count);
        for shard in &self.shards {
            let trucks = shard.read().await;
            readings.extend(trucks.iter().filter_map(|t| t.temperature_reading()));
        }
        readings
    }

    /// Get active anomalies across all shards.
    pub async fn active_anomalies(&self) -> Vec<(String, String)> {
        let mut anomalies = Vec::new();
        for shard in &self.shards {
            let trucks = shard.read().await;
            for t in trucks.iter() {
                if let Some(a) = &t.anomaly_active {
                    anomalies.push((t.truck_id.clone(), a.clone()));
                }
            }
        }
        anomalies
    }

    /// Mutate a single truck by ID — only locks the target shard.
    pub async fn with_truck_mut<F>(&self, truck_id: &str, f: F) -> bool
    where
        F: FnOnce(&mut Truck),
    {
        let Some(shard_idx) = self.shard_for_id(truck_id) else {
            return false;
        };
        let mut trucks = self.shards[shard_idx].write().await;
        if let Some(truck) = trucks.iter_mut().find(|t| t.truck_id == truck_id) {
            f(truck);
            true
        } else {
            false
        }
    }

    /// Reset all trucks — processes shards sequentially.
    pub async fn reset_all(&self) {
        for shard in &self.shards {
            let mut trucks = shard.write().await;
            for truck in trucks.iter_mut() {
                truck.anomaly_active = None;
                truck.speed_kmh = 80.0;
            }
        }
    }
}

/// Create individual trucks (internal).
/// Uses OSRM routes if available, falls back to hardcoded ROUTES.
fn create_trucks(
    truck_count: usize,
    refrigerated_count: usize,
    osrm_routes: &[(String, Vec<(f64, f64)>)],
) -> Vec<Truck> {
    let mut rng = rand::thread_rng();
    let mut trucks = Vec::with_capacity(truck_count);

    let perishable: Vec<&CargoType> = CARGO_TYPES.iter().filter(|c| c.perishable).collect();
    let non_perishable: Vec<&CargoType> = CARGO_TYPES.iter().filter(|c| !c.perishable).collect();

    let use_osrm = !osrm_routes.is_empty();

    for i in 0..truck_count {
        let (route_name, waypoints): (String, Vec<(f64, f64)>) = if use_osrm {
            let idx = rng.gen_range(0..osrm_routes.len());
            (osrm_routes[idx].0.clone(), osrm_routes[idx].1.clone())
        } else {
            let idx = rng.gen_range(0..ROUTES.len());
            let (name, wps) = ROUTES[idx];
            (name.to_string(), wps.to_vec())
        };

        let is_refrigerated = i < refrigerated_count;
        let cargo = if is_refrigerated {
            perishable[rng.gen_range(0..perishable.len())].clone()
        } else {
            non_perishable[rng.gen_range(0..non_perishable.len())].clone()
        };

        let max_wp_idx = waypoints.len().saturating_sub(2);
        // Step size adapts to waypoint density: more waypoints = larger step per segment
        // so total route traversal time stays constant (~22K ticks regardless of density).
        // 44 segments → step 0.002, 499 segments → step 0.0227
        let segments = waypoints.len().saturating_sub(1).max(1) as f64;
        let tick_step = segments / 22_000.0;
        let truck = Truck {
            truck_id: format!("truck-{:05}", i),
            route_name,
            route_waypoints: waypoints,
            cargo,
            client: CLIENTS[rng.gen_range(0..CLIENTS.len())].to_string(),
            refrigerated: is_refrigerated,
            current_waypoint_idx: rng.gen_range(0..=max_wp_idx),
            progress_between: rng.gen::<f64>(),
            speed_kmh: 80.0,
            engine_on: true,
            anomaly_active: None,
            forward: true,
            tick_step,
        };
        trucks.push(truck);
    }

    trucks
}
