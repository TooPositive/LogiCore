//! Fleet data generators — trucks, GPS pings, temperature readings.
//!
//! Each truck follows a real European route defined as waypoints (lat/lng).
//! GPS pings interpolate between waypoints at realistic speeds.
//! Temperature readings hover around set point with random noise.

use chrono::Utc;
use rand::Rng;
use serde::Serialize;
use tokio::sync::RwLock;

/// Real European highway waypoints (simplified).
pub const ROUTES: &[(&str, &[(f64, f64)])] = &[
    ("hamburg-zurich", &[
        (53.55, 9.99),   // Hamburg
        (52.37, 9.74),   // Hannover
        (50.94, 6.96),   // Cologne
        (49.45, 8.65),   // Mannheim
        (48.78, 9.18),   // Stuttgart
        (47.38, 8.54),   // Zurich
    ]),
    ("amsterdam-munich", &[
        (52.37, 4.90),   // Amsterdam
        (51.44, 5.47),   // Eindhoven
        (50.94, 6.96),   // Cologne
        (50.11, 8.68),   // Frankfurt
        (49.01, 12.10),  // Regensburg
        (48.14, 11.58),  // Munich
    ]),
    ("rotterdam-vienna", &[
        (51.92, 4.48),   // Rotterdam
        (50.94, 6.96),   // Cologne
        (50.11, 8.68),   // Frankfurt
        (49.45, 11.08),  // Nuremberg
        (48.31, 14.29),  // Linz
        (48.21, 16.37),  // Vienna
    ]),
    ("berlin-milan", &[
        (52.52, 13.40),  // Berlin
        (51.34, 12.37),  // Leipzig
        (49.01, 12.10),  // Regensburg
        (48.14, 11.58),  // Munich
        (47.27, 11.39),  // Innsbruck
        (46.07, 11.12),  // Trento
        (45.46, 9.19),   // Milan
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

        // Move forward
        self.progress_between += 0.002 + rng.gen_range(-0.0005..0.0005);
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
    pub fn new(truck_count: usize, refrigerated_count: usize, shard_count: usize) -> Self {
        let shard_count = if shard_count == 0 {
            (truck_count / 16).max(1)
        } else {
            shard_count
        };

        let trucks = create_trucks(truck_count, refrigerated_count);
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
fn create_trucks(truck_count: usize, refrigerated_count: usize) -> Vec<Truck> {
    let mut rng = rand::thread_rng();
    let mut trucks = Vec::with_capacity(truck_count);

    let perishable: Vec<&CargoType> = CARGO_TYPES.iter().filter(|c| c.perishable).collect();
    let non_perishable: Vec<&CargoType> = CARGO_TYPES.iter().filter(|c| !c.perishable).collect();

    for i in 0..truck_count {
        let route_idx = rng.gen_range(0..ROUTES.len());
        let (route_name, waypoints) = ROUTES[route_idx];
        let is_refrigerated = i < refrigerated_count;

        let cargo = if is_refrigerated {
            perishable[rng.gen_range(0..perishable.len())].clone()
        } else {
            non_perishable[rng.gen_range(0..non_perishable.len())].clone()
        };

        let max_wp_idx = waypoints.len() - 2;
        let truck = Truck {
            truck_id: format!("truck-{:04}", i),
            route_name: route_name.to_string(),
            route_waypoints: waypoints.to_vec(),
            cargo,
            client: CLIENTS[rng.gen_range(0..CLIENTS.len())].to_string(),
            refrigerated: is_refrigerated,
            current_waypoint_idx: rng.gen_range(0..=max_wp_idx),
            progress_between: rng.gen::<f64>(),
            speed_kmh: 80.0,
            engine_on: true,
            anomaly_active: None,
            forward: true,
        };
        trucks.push(truck);
    }

    trucks
}
