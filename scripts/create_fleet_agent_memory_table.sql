-- Fleet Agent Memory: long-term learned patterns from anomaly investigations.
-- Used by the Fleet Guardian agent for cross-session memory (Phase 9).
--
-- Stores confirmed patterns (recurring failures, false positives) that
-- inform future anomaly responses. Indefinite retention, manual pruning.

CREATE TABLE IF NOT EXISTS fleet_agent_memory (
    memory_id    BIGSERIAL PRIMARY KEY,
    truck_id     TEXT        NOT NULL,
    pattern      TEXT        NOT NULL,
    alert_type   TEXT        NOT NULL,
    action_taken TEXT        NOT NULL,
    outcome      TEXT        NOT NULL DEFAULT 'pending_verification',
    learned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

-- Index for fast per-truck lookups (the most common query pattern)
CREATE INDEX IF NOT EXISTS idx_fleet_agent_memory_truck_id
    ON fleet_agent_memory (truck_id);

-- Index for pattern-based queries across the entire fleet
CREATE INDEX IF NOT EXISTS idx_fleet_agent_memory_pattern
    ON fleet_agent_memory (pattern);

-- Index for time-based queries (recent patterns first)
CREATE INDEX IF NOT EXISTS idx_fleet_agent_memory_learned_at
    ON fleet_agent_memory (learned_at DESC);

-- Comments for documentation
COMMENT ON TABLE fleet_agent_memory IS 'Long-term agent memory: learned patterns from fleet anomaly investigations';
COMMENT ON COLUMN fleet_agent_memory.pattern IS 'Pattern name (e.g., recurring_refrigeration_failure)';
COMMENT ON COLUMN fleet_agent_memory.outcome IS 'Resolution status: pending_verification, verified_fixed, false_positive';
