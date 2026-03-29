use std::sync::Arc;

use axum::{
    extract::{Query, State},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};

use crate::fleet::ShardedFleet;
use crate::mock_data;

pub type FleetState = Arc<ShardedFleet>;

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    truck_count: usize,
    shard_count: usize,
}

#[derive(Debug, Serialize)]
struct TriggerResponse {
    triggered: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    truck_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    invoice_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    duration_seconds: Option<u32>,
}

#[derive(Debug, Serialize)]
struct ResetResponse {
    status: &'static str,
    active_scenarios: Vec<String>,
}

#[derive(Debug, Serialize)]
struct FleetStatusResponse {
    total_trucks: usize,
    refrigerated: usize,
    shard_count: usize,
    active_anomalies: Vec<AnomalyInfo>,
}

#[derive(Debug, Serialize)]
struct AnomalyInfo {
    truck_id: String,
    anomaly: String,
}

#[derive(Debug, Deserialize)]
struct TruckIdParam {
    #[serde(default = "default_truck_temp")]
    truck_id: String,
}

fn default_truck_temp() -> String {
    "truck-4721".to_string()
}

#[derive(Debug, Deserialize)]
struct RouteDeviationParam {
    #[serde(default = "default_truck_route")]
    truck_id: String,
}

fn default_truck_route() -> String {
    "truck-1138".to_string()
}

#[derive(Debug, Deserialize)]
struct BorderCrossingParam {
    #[serde(default = "default_truck_border")]
    truck_id: String,
}

fn default_truck_border() -> String {
    "truck-2205".to_string()
}

#[derive(Debug, Deserialize)]
struct SpeedAnomalyParam {
    #[serde(default = "default_truck_speed")]
    truck_id: String,
}

fn default_truck_speed() -> String {
    "truck-0892".to_string()
}

#[derive(Debug, Deserialize)]
struct BillingParam {
    #[serde(default = "default_invoice")]
    invoice_id: String,
}

fn default_invoice() -> String {
    "INV-2024-0847".to_string()
}

#[derive(Debug, Deserialize)]
struct OutageParam {
    #[serde(default = "default_duration")]
    duration_seconds: u32,
}

fn default_duration() -> u32 {
    30
}

pub fn router() -> Router<FleetState> {
    Router::new()
        .route("/health", get(health))
        .route("/fleet/status", get(fleet_status))
        .route("/fleet/snapshot", get(fleet_snapshot))
        .route("/fleet/temperatures", get(fleet_temperatures))
        .route("/simulator/trigger/temperature-spike", post(trigger_temperature_spike))
        .route("/simulator/trigger/route-deviation", post(trigger_route_deviation))
        .route("/simulator/trigger/border-crossing", post(trigger_border_crossing))
        .route("/simulator/trigger/speed-anomaly", post(trigger_speed_anomaly))
        .route("/simulator/trigger/billing-discrepancy", post(trigger_billing_discrepancy))
        .route("/simulator/trigger/prompt-injection", post(trigger_prompt_injection))
        .route("/simulator/trigger/azure-outage", post(trigger_azure_outage))
        .route("/simulator/reset", post(reset_all))
        .route("/data/company", get(get_company))
        .route("/data/warehouses", get(get_warehouses))
        .route("/data/contracts", get(get_contracts))
        .route("/data/invoices", get(get_invoices))
        .route("/data/documents", get(get_documents))
        .route("/data/users", get(get_users))
}

// --- Health & Status ---

async fn health(State(fleet): State<FleetState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        service: "logicore-simulator",
        version: "0.1.0",
        truck_count: fleet.total_trucks(),
        shard_count: fleet.shard_count(),
    })
}

async fn fleet_status(State(fleet): State<FleetState>) -> Json<FleetStatusResponse> {
    let anomalies = fleet.active_anomalies().await;
    Json(FleetStatusResponse {
        total_trucks: fleet.total_trucks(),
        refrigerated: fleet.refrigerated_count(),
        shard_count: fleet.shard_count(),
        active_anomalies: anomalies
            .into_iter()
            .map(|(truck_id, anomaly)| AnomalyInfo { truck_id, anomaly })
            .collect(),
    })
}

async fn fleet_snapshot(State(fleet): State<FleetState>) -> Json<Vec<crate::fleet::GpsPing>> {
    Json(fleet.snapshot_all().await)
}

async fn fleet_temperatures(State(fleet): State<FleetState>) -> Json<Vec<crate::fleet::TemperatureReading>> {
    Json(fleet.temperatures_all().await)
}

// --- Scenario Triggers (each locks only ONE shard) ---

async fn trigger_temperature_spike(
    State(fleet): State<FleetState>,
    Query(params): Query<TruckIdParam>,
) -> Json<TriggerResponse> {
    fleet.with_truck_mut(&params.truck_id, |truck| {
        truck.anomaly_active = Some("temperature-spike".to_string());
    }).await;
    Json(TriggerResponse {
        triggered: "temperature-spike".to_string(),
        truck_id: Some(params.truck_id),
        invoice_id: None,
        duration_seconds: None,
    })
}

async fn trigger_route_deviation(
    State(fleet): State<FleetState>,
    Query(params): Query<RouteDeviationParam>,
) -> Json<TriggerResponse> {
    fleet.with_truck_mut(&params.truck_id, |truck| {
        truck.anomaly_active = Some("route-deviation".to_string());
    }).await;
    Json(TriggerResponse {
        triggered: "route-deviation".to_string(),
        truck_id: Some(params.truck_id),
        invoice_id: None,
        duration_seconds: None,
    })
}

async fn trigger_border_crossing(
    State(fleet): State<FleetState>,
    Query(params): Query<BorderCrossingParam>,
) -> Json<TriggerResponse> {
    fleet.with_truck_mut(&params.truck_id, |truck| {
        truck.anomaly_active = Some("border-crossing".to_string());
    }).await;
    Json(TriggerResponse {
        triggered: "border-crossing".to_string(),
        truck_id: Some(params.truck_id),
        invoice_id: None,
        duration_seconds: None,
    })
}

async fn trigger_speed_anomaly(
    State(fleet): State<FleetState>,
    Query(params): Query<SpeedAnomalyParam>,
) -> Json<TriggerResponse> {
    fleet.with_truck_mut(&params.truck_id, |truck| {
        truck.anomaly_active = Some("speed-anomaly".to_string());
        truck.speed_kmh = 135.0;
    }).await;
    Json(TriggerResponse {
        triggered: "speed-anomaly".to_string(),
        truck_id: Some(params.truck_id),
        invoice_id: None,
        duration_seconds: None,
    })
}

async fn trigger_billing_discrepancy(
    Query(params): Query<BillingParam>,
) -> Json<TriggerResponse> {
    Json(TriggerResponse {
        triggered: "billing-discrepancy".to_string(),
        truck_id: None,
        invoice_id: Some(params.invoice_id),
        duration_seconds: None,
    })
}

async fn trigger_prompt_injection() -> Json<TriggerResponse> {
    Json(TriggerResponse {
        triggered: "prompt-injection".to_string(),
        truck_id: None,
        invoice_id: None,
        duration_seconds: None,
    })
}

async fn trigger_azure_outage(
    Query(params): Query<OutageParam>,
) -> Json<TriggerResponse> {
    Json(TriggerResponse {
        triggered: "azure-outage".to_string(),
        truck_id: None,
        invoice_id: None,
        duration_seconds: Some(params.duration_seconds),
    })
}

async fn reset_all(State(fleet): State<FleetState>) -> Json<ResetResponse> {
    fleet.reset_all().await;
    Json(ResetResponse {
        status: "reset",
        active_scenarios: vec![],
    })
}

// --- Static Data Endpoints ---

async fn get_company() -> Json<mock_data::Company> {
    Json(mock_data::COMPANY)
}

async fn get_warehouses() -> Json<&'static [mock_data::Warehouse]> {
    Json(mock_data::WAREHOUSES)
}

async fn get_contracts() -> Json<&'static [mock_data::Contract]> {
    Json(mock_data::CONTRACTS)
}

async fn get_invoices() -> Json<&'static [mock_data::Invoice]> {
    Json(mock_data::INVOICES)
}

async fn get_documents() -> Json<&'static [mock_data::Document]> {
    Json(mock_data::DOCUMENTS)
}

async fn get_users() -> Json<&'static [mock_data::User]> {
    Json(mock_data::USERS)
}
