mod config;
mod fleet;
mod mock_data;
mod routes;

use std::sync::Arc;
use std::time::Duration;

use tower_http::cors::CorsLayer;
use tracing::info;

use config::Config;
use fleet::ShardedFleet;
use routes::router;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "logicore_simulator=info".into()),
        )
        .init();

    let config = Config::from_env();

    let fleet = Arc::new(ShardedFleet::new(
        config.truck_count,
        config.refrigerated_count,
        config.shard_count,
    ));

    info!(
        "LogiCore Simulator starting — {} trucks ({} refrigerated), {} shards",
        fleet.total_trucks(),
        fleet.refrigerated_count(),
        fleet.shard_count(),
    );

    // Background simulation loop — GPS ticks (shard-sequential, each lock held briefly)
    let gps_fleet = Arc::clone(&fleet);
    let gps_interval = config.gps_interval_ms;
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(gps_interval));
        loop {
            interval.tick().await;
            gps_fleet.tick_all().await;
        }
    });

    // Background simulation loop — temperature readings + optional Kafka publish
    let temp_fleet = Arc::clone(&fleet);
    let temp_interval = config.temperature_interval_ms;
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(temp_interval));

        #[cfg(feature = "kafka")]
        let producer = create_kafka_producer(&config.kafka_bootstrap_servers);

        loop {
            interval.tick().await;
            let readings = temp_fleet.temperatures_all().await;

            if !readings.is_empty() {
                #[cfg(feature = "kafka")]
                publish_readings(&producer, &readings).await;

                let _ = readings;
            }
        }
    });

    let app = router()
        .layer(CorsLayer::permissive())
        .with_state(fleet);

    let addr = format!("0.0.0.0:{}", config.port);
    info!("Listening on {addr}");

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

#[cfg(feature = "kafka")]
fn create_kafka_producer(brokers: &str) -> rdkafka::producer::FutureProducer {
    use rdkafka::config::ClientConfig;
    use rdkafka::producer::FutureProducer;

    ClientConfig::new()
        .set("bootstrap.servers", brokers)
        .set("message.timeout.ms", "5000")
        .create::<FutureProducer>()
        .expect("Failed to create Kafka producer")
}

#[cfg(feature = "kafka")]
async fn publish_readings(
    producer: &rdkafka::producer::FutureProducer,
    readings: &[fleet::TemperatureReading],
) {
    use rdkafka::producer::FutureRecord;
    use tracing::warn;

    for reading in readings {
        let payload = serde_json::to_string(reading).unwrap();
        let key = &reading.truck_id;
        let record = FutureRecord::to("fleet.temperature")
            .key(key)
            .payload(&payload);

        if let Err((err, _)) = producer.send(record, Duration::from_secs(1)).await {
            warn!("Kafka publish failed: {err}");
        }
    }
}
