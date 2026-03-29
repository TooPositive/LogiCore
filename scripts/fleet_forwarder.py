#!/usr/bin/env python3
"""Fleet telemetry forwarder: bridges simulator → FastAPI backend.

Polls the simulator for temperature readings and GPS pings,
then forwards them to the backend's direct ingest endpoints.
The backend's AnomalyDetector processes them and broadcasts
alerts via WebSocket to the dashboard.

Usage:
    python scripts/fleet_forwarder.py

Env vars:
    SIMULATOR_URL  (default: http://localhost:8081)
    BACKEND_URL    (default: http://localhost:8080)
    POLL_INTERVAL  (default: 5, seconds)
    GPS_SAMPLE     (default: 100, random trucks per cycle)
"""

import asyncio
import os
import random
import signal
import sys

import httpx

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8081")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
GPS_SAMPLE = int(os.getenv("GPS_SAMPLE", "100"))

running = True


def handle_signal(sig: int, frame: object) -> None:
    global running
    running = False
    print("\nShutting down...")


TEMP_SAMPLE = int(os.getenv("TEMP_SAMPLE", "30"))


async def _post(client: httpx.AsyncClient, url: str, payload: dict) -> int:
    """POST and return alert count."""
    try:
        resp = await client.post(url, json=payload, timeout=5.0)
        if resp.status_code == 200:
            return len(resp.json().get("alerts", []))
    except httpx.RequestError:
        pass
    return 0


async def forward_temperatures(
    client: httpx.AsyncClient,
    readings: list[dict],
) -> int:
    """Forward sampled temperature readings to the backend concurrently."""
    sample = random.sample(readings, min(TEMP_SAMPLE, len(readings)))
    tasks = []
    for r in sample:
        payload = {
            "truck_id": r["truck_id"],
            "sensor_id": r.get("sensor_id", f"{r['truck_id']}-temp-01"),
            "temp_celsius": r["temp_celsius"],
            "setpoint_celsius": r["setpoint_celsius"],
            "cargo_type": r.get("cargo_type", "unknown"),
            "cargo_value_eur": r.get("cargo_value_eur", 0),
            "timestamp": r["timestamp"],
        }
        tasks.append(
            _post(client, f"{BACKEND_URL}/api/v1/fleet/ingest/temperature", payload)
        )
    results = await asyncio.gather(*tasks)
    return sum(results)


async def forward_gps(
    client: httpx.AsyncClient,
    pings: list[dict],
) -> int:
    """Forward sampled GPS pings to the backend concurrently."""
    sample = random.sample(pings, min(GPS_SAMPLE, len(pings)))
    tasks = []
    for p in sample:
        payload = {
            "truck_id": p["truck_id"],
            "latitude": p["lat"],
            "longitude": p["lng"],
            "speed_kmh": p["speed_kmh"],
            "heading": 0.0,
            "timestamp": p["timestamp"],
            "engine_on": p.get("engine_on", True),
        }
        tasks.append(
            _post(client, f"{BACKEND_URL}/api/v1/fleet/ingest/gps", payload)
        )
    results = await asyncio.gather(*tasks)
    return sum(results)


async def main() -> None:
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Fleet Forwarder starting")
    print(f"  Simulator: {SIMULATOR_URL}")
    print(f"  Backend:   {BACKEND_URL}")
    print(f"  Interval:  {POLL_INTERVAL}s")
    print(f"  GPS sample: {GPS_SAMPLE} trucks/cycle")

    async with httpx.AsyncClient() as client:
        # Wait for both services
        for svc, url in [
            ("Simulator", f"{SIMULATOR_URL}/health"),
            ("Backend", f"{BACKEND_URL}/api/v1/health"),
        ]:
            while running:
                try:
                    r = await client.get(url, timeout=3.0)
                    if r.status_code == 200:
                        print(f"  {svc}: online")
                        break
                except httpx.RequestError:
                    pass
                print(f"  Waiting for {svc}...")
                await asyncio.sleep(2)

        cycle = 0
        total_msgs = 0
        total_alerts = 0

        while running:
            try:
                # Fetch from simulator
                temps_resp = await client.get(
                    f"{SIMULATOR_URL}/fleet/temperatures", timeout=5.0
                )
                gps_resp = await client.get(
                    f"{SIMULATOR_URL}/fleet/snapshot", timeout=10.0
                )

                temps = temps_resp.json() if temps_resp.status_code == 200 else []
                pings = gps_resp.json() if gps_resp.status_code == 200 else []

                # Forward to backend
                t_alerts = await forward_temperatures(client, temps)
                g_alerts = await forward_gps(client, pings)

                msgs = min(TEMP_SAMPLE, len(temps)) + min(GPS_SAMPLE, len(pings))
                total_msgs += msgs
                total_alerts += t_alerts + g_alerts
                cycle += 1

                if cycle % 6 == 1:  # Log every ~30s
                    print(
                        f"  [cycle {cycle}] "
                        f"forwarded {msgs} msgs "
                        f"({len(temps)} temps + {min(GPS_SAMPLE, len(pings))} gps), "
                        f"{t_alerts + g_alerts} new alerts "
                        f"(total: {total_msgs} msgs, {total_alerts} alerts)"
                    )

            except httpx.RequestError as e:
                print(f"  Error: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    print(
        f"Forwarder stopped. Total: {total_msgs} messages, {total_alerts} alerts"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
