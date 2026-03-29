"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { FleetAlert } from "./types";
import { fleet } from "./api";

const MAX_ALERTS = 50;

export function useFleetWebSocket() {
  const [alerts, setAlerts] = useState<FleetAlert[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const reconnectDelay = useRef(1000);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(fleet.wsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectDelay.current = 1000;
      };

      ws.onmessage = (event) => {
        if (event.data === "pong") return;
        try {
          const alert = JSON.parse(event.data) as FleetAlert;
          setAlerts((prev) => [alert, ...prev].slice(0, MAX_ALERTS));
        } catch {
          // ignore non-JSON messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimer.current = setTimeout(() => {
          reconnectDelay.current = Math.min(reconnectDelay.current * 2, 10000);
          connect();
        }, reconnectDelay.current);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    connect();
    // Keepalive ping every 30s
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 30000);

    return () => {
      clearInterval(ping);
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { alerts, connected };
}
