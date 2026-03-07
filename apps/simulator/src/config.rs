use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub truck_count: usize,
    pub refrigerated_count: usize,
    pub gps_interval_ms: u64,
    pub temperature_interval_ms: u64,
    pub anomaly_probability: f64,
    pub shard_count: usize,
    pub kafka_bootstrap_servers: String,
    pub port: u16,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            truck_count: env_or("TRUCK_COUNT", 50),
            refrigerated_count: env_or("REFRIGERATED_COUNT", 15),
            gps_interval_ms: env_or("GPS_INTERVAL_MS", 2000),
            temperature_interval_ms: env_or("TEMPERATURE_INTERVAL_MS", 5000),
            anomaly_probability: env_or("ANOMALY_PROBABILITY", 0.001),
            shard_count: env_or("SHARD_COUNT", 0), // 0 = auto (truck_count / 16, min 1)
            kafka_bootstrap_servers: env::var("KAFKA_BOOTSTRAP_SERVERS")
                .unwrap_or_else(|_| "kafka:29092".to_string()),
            port: env_or("PORT", 8081),
        }
    }
}

fn env_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}
