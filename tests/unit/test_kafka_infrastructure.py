"""Unit tests for core Kafka infrastructure.

Tests consumer base class and producer helper.
All tests use mocks -- no real Kafka needed.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── KafkaProducerHelper ──────────────────────────────────────────────────────


class TestKafkaProducerHelper:
    """Tests for the domain-agnostic Kafka producer wrapper."""

    async def test_producer_send_serializes_json(self):
        from apps.api.src.core.infrastructure.kafka.producer import KafkaProducerHelper

        mock_producer = AsyncMock()
        helper = KafkaProducerHelper(producer=mock_producer)

        await helper.send(
            topic="fleet.alerts",
            value={"truck_id": "truck-001", "alert_type": "temperature_spike"},
            key="truck-001",
        )

        mock_producer.send_and_wait.assert_called_once()
        call_args = mock_producer.send_and_wait.call_args
        assert call_args.kwargs["topic"] == "fleet.alerts"
        # Value should be bytes (JSON serialized)
        assert isinstance(call_args.kwargs["value"], bytes)

    async def test_producer_send_with_key(self):
        from apps.api.src.core.infrastructure.kafka.producer import KafkaProducerHelper

        mock_producer = AsyncMock()
        helper = KafkaProducerHelper(producer=mock_producer)

        await helper.send(
            topic="fleet.temperature",
            value={"temp": 3.2},
            key="truck-4721",
        )

        call_args = mock_producer.send_and_wait.call_args
        assert call_args.kwargs["key"] == b"truck-4721"

    async def test_producer_send_without_key(self):
        from apps.api.src.core.infrastructure.kafka.producer import KafkaProducerHelper

        mock_producer = AsyncMock()
        helper = KafkaProducerHelper(producer=mock_producer)

        await helper.send(
            topic="fleet.gps-pings",
            value={"lat": 47.37},
        )

        call_args = mock_producer.send_and_wait.call_args
        assert call_args.kwargs["key"] is None

    async def test_producer_start_and_stop(self):
        from apps.api.src.core.infrastructure.kafka.producer import KafkaProducerHelper

        mock_producer = AsyncMock()
        helper = KafkaProducerHelper(producer=mock_producer)

        await helper.start()
        mock_producer.start.assert_called_once()

        await helper.stop()
        mock_producer.stop.assert_called_once()

    async def test_producer_send_batch(self):
        from apps.api.src.core.infrastructure.kafka.producer import KafkaProducerHelper

        mock_producer = AsyncMock()
        helper = KafkaProducerHelper(producer=mock_producer)

        messages = [
            {"truck_id": f"truck-{i}", "temp": 3.0 + i * 0.1}
            for i in range(5)
        ]
        await helper.send_batch(topic="fleet.temperature", values=messages)

        assert mock_producer.send_and_wait.call_count == 5


# ── KafkaConsumerWorker ──────────────────────────────────────────────────────


class TestKafkaConsumerWorker:
    """Tests for the domain-agnostic Kafka consumer base class."""

    async def test_consumer_handler_receives_deserialized_message(self):
        """Consumer should deserialize JSON and pass dict to handler."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        received = []

        async def handler(msg: dict) -> None:
            received.append(msg)

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        # Simulate processing a message
        mock_msg = MagicMock()
        mock_msg.value = b'{"truck_id": "truck-001", "temp": 6.1}'
        mock_msg.topic = "fleet.temperature"
        mock_msg.partition = 0
        mock_msg.offset = 42

        await worker._process_message(mock_msg)

        assert len(received) == 1
        assert received[0]["truck_id"] == "truck-001"
        assert received[0]["temp"] == 6.1

    async def test_consumer_handles_invalid_json_gracefully(self):
        """Invalid JSON should log error, not crash consumer."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        received = []

        async def handler(msg: dict) -> None:
            received.append(msg)

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        mock_msg = MagicMock()
        mock_msg.value = b"not valid json"
        mock_msg.topic = "fleet.temperature"
        mock_msg.partition = 0
        mock_msg.offset = 99

        # Should not raise
        await worker._process_message(mock_msg)
        assert len(received) == 0

    async def test_consumer_tracks_health_status(self):
        """Consumer should report whether it's healthy (processing messages)."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        async def handler(msg: dict) -> None:
            pass

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        # Before starting, not healthy
        assert worker.is_healthy is False

    async def test_consumer_configuration(self):
        """Consumer should store topic and group configuration."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        async def handler(msg: dict) -> None:
            pass

        worker = KafkaConsumerWorker(
            topics=["fleet.gps-pings", "fleet.temperature"],
            group_id="fleet-guardian",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        assert worker.topics == ["fleet.gps-pings", "fleet.temperature"]
        assert worker.group_id == "fleet-guardian"

    async def test_consumer_message_counter_increments(self):
        """Consumer should track how many messages it has processed."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        async def handler(msg: dict) -> None:
            pass

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        assert worker.messages_processed == 0

        mock_msg = MagicMock()
        mock_msg.value = b'{"truck_id": "truck-001"}'
        mock_msg.topic = "fleet.temperature"
        mock_msg.partition = 0
        mock_msg.offset = 0

        await worker._process_message(mock_msg)
        assert worker.messages_processed == 1

        await worker._process_message(mock_msg)
        assert worker.messages_processed == 2

    async def test_consumer_handler_error_does_not_crash(self):
        """Handler errors should be caught and logged, not crash the consumer."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        async def failing_handler(msg: dict) -> None:
            raise ValueError("Processing failed!")

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=failing_handler,
            bootstrap_servers="localhost:9092",
        )

        mock_msg = MagicMock()
        mock_msg.value = b'{"truck_id": "truck-001"}'
        mock_msg.topic = "fleet.temperature"
        mock_msg.partition = 0
        mock_msg.offset = 0

        # Should not raise
        await worker._process_message(mock_msg)
        # Error count should be tracked
        assert worker.errors == 1

    async def test_consumer_last_message_timestamp(self):
        """Consumer should track when it last processed a message."""
        from apps.api.src.core.infrastructure.kafka.consumer import KafkaConsumerWorker

        async def handler(msg: dict) -> None:
            pass

        worker = KafkaConsumerWorker(
            topics=["fleet.temperature"],
            group_id="test-group",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )

        assert worker.last_message_at is None

        mock_msg = MagicMock()
        mock_msg.value = b'{"truck_id": "truck-001"}'
        mock_msg.topic = "fleet.temperature"
        mock_msg.partition = 0
        mock_msg.offset = 0

        before = datetime.now(UTC)
        await worker._process_message(mock_msg)

        assert worker.last_message_at is not None
        assert worker.last_message_at >= before
