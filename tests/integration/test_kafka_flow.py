"""Integration tests for Kafka producer -> consumer flow.

Requires a real Kafka broker at localhost:9092 (Docker).
Run: docker compose --profile kafka up -d
Skip: pytest -m "not kafka" (or just run pytest -- these are skipped by default).

CTO QUESTION: "You have consumer/producer classes but no test against a real Kafka
broker. How do you know this works under real conditions?"
ANSWER: These tests prove JSON round-trip, consumer health tracking, and message
ordering work with a real Kafka broker, not just mocks.
"""

import asyncio
import json
import uuid

import pytest

# Skip all tests if Kafka is not available
pytestmark = [pytest.mark.kafka, pytest.mark.integration]


def _kafka_available() -> bool:
    """Check if Kafka is reachable at localhost:9092."""
    import socket

    try:
        sock = socket.create_connection(("localhost", 9092), timeout=2)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


skip_no_kafka = pytest.mark.skipif(
    not _kafka_available(),
    reason="Kafka not available at localhost:9092 (run: docker compose --profile kafka up -d)",
)


@skip_no_kafka
class TestKafkaProducerConsumer:
    """Real Kafka producer -> consumer flow tests."""

    async def test_produce_and_consume_json_message(self):
        """Produce a JSON message, consume it, verify round-trip."""
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

        from apps.api.src.core.infrastructure.kafka.producer import (
            KafkaProducerHelper,
        )

        topic = f"test-roundtrip-{uuid.uuid4().hex[:8]}"
        test_message = {
            "truck_id": "truck-kafka-test",
            "sensor_id": "sensor-01",
            "temp_celsius": 12.5,
            "timestamp": "2026-03-10T03:01:30+00:00",
        }

        # Produce
        raw_producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        producer = KafkaProducerHelper(raw_producer)
        await producer.start()
        await producer.send(topic=topic, value=test_message, key="truck-kafka-test")
        await producer.stop()

        # Consume directly (not via KafkaConsumerWorker, to verify the raw message)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers="localhost:9092",
            auto_offset_reset="earliest",
            group_id=f"test-group-{uuid.uuid4().hex[:8]}",
            consumer_timeout_ms=5000,
        )
        await consumer.start()

        received = None
        try:
            async for msg in consumer:
                received = json.loads(msg.value)
                break
        finally:
            await consumer.stop()

        assert received is not None, "No message received from Kafka"
        assert received["truck_id"] == "truck-kafka-test"
        assert received["temp_celsius"] == 12.5

    async def test_consumer_worker_processes_message(self):
        """KafkaConsumerWorker receives and processes a real Kafka message."""
        from aiokafka import AIOKafkaProducer

        from apps.api.src.core.infrastructure.kafka.consumer import (
            KafkaConsumerWorker,
        )
        from apps.api.src.core.infrastructure.kafka.producer import (
            KafkaProducerHelper,
        )

        topic = f"test-worker-{uuid.uuid4().hex[:8]}"
        received_messages: list[dict] = []

        async def handler(data: dict) -> None:
            received_messages.append(data)

        # Start consumer worker
        worker = KafkaConsumerWorker(
            topics=[topic],
            group_id=f"test-group-{uuid.uuid4().hex[:8]}",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )
        await worker.start()

        # Run consumer in background
        consumer_task = asyncio.create_task(worker.run())

        # Give consumer time to subscribe
        await asyncio.sleep(1)

        # Produce a message
        raw_producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        producer = KafkaProducerHelper(raw_producer)
        await producer.start()
        await producer.send(
            topic=topic,
            value={"truck_id": "truck-worker-test", "temp_celsius": 9.5},
            key="truck-worker-test",
        )
        await producer.stop()

        # Wait for message to be consumed
        for _ in range(50):
            if received_messages:
                break
            await asyncio.sleep(0.1)

        await worker.stop()
        consumer_task.cancel()

        assert len(received_messages) == 1
        assert received_messages[0]["truck_id"] == "truck-worker-test"
        assert worker.messages_processed == 1
        assert worker.is_healthy is False  # stopped
        assert worker.last_message_at is not None

    async def test_consumer_health_metrics_update(self):
        """Consumer health metrics (messages_processed, last_message_at) update correctly."""
        from aiokafka import AIOKafkaProducer

        from apps.api.src.core.infrastructure.kafka.consumer import (
            KafkaConsumerWorker,
        )
        from apps.api.src.core.infrastructure.kafka.producer import (
            KafkaProducerHelper,
        )

        topic = f"test-health-{uuid.uuid4().hex[:8]}"
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        worker = KafkaConsumerWorker(
            topics=[topic],
            group_id=f"test-group-{uuid.uuid4().hex[:8]}",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )
        await worker.start()
        assert worker.is_healthy is True
        assert worker.messages_processed == 0
        assert worker.last_message_at is None

        consumer_task = asyncio.create_task(worker.run())
        await asyncio.sleep(1)

        # Send 3 messages
        raw_producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        producer = KafkaProducerHelper(raw_producer)
        await producer.start()
        for i in range(3):
            await producer.send(
                topic=topic,
                value={"truck_id": f"truck-{i}", "seq": i},
            )
        await producer.stop()

        # Wait for all messages
        for _ in range(50):
            if len(received) >= 3:
                break
            await asyncio.sleep(0.1)

        assert worker.messages_processed == 3
        assert worker.last_message_at is not None

        await worker.stop()
        consumer_task.cancel()

    async def test_consumer_handles_invalid_json_gracefully(self):
        """Invalid JSON in a Kafka message should not crash the consumer."""
        from aiokafka import AIOKafkaProducer

        from apps.api.src.core.infrastructure.kafka.consumer import (
            KafkaConsumerWorker,
        )

        topic = f"test-invalid-{uuid.uuid4().hex[:8]}"
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        worker = KafkaConsumerWorker(
            topics=[topic],
            group_id=f"test-group-{uuid.uuid4().hex[:8]}",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )
        await worker.start()
        consumer_task = asyncio.create_task(worker.run())
        await asyncio.sleep(1)

        # Send invalid JSON directly (raw producer, not helper)
        raw_producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        await raw_producer.start()
        await raw_producer.send_and_wait(
            topic=topic,
            value=b"not valid json {{{}",
        )
        # Then send a valid message
        valid_bytes = json.dumps({"truck_id": "truck-after-invalid", "valid": True}).encode()
        await raw_producer.send_and_wait(topic=topic, value=valid_bytes)
        await raw_producer.stop()

        # Wait for processing
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.1)

        assert worker.errors >= 1, "Invalid JSON should increment error count"
        assert len(received) >= 1, "Valid message after invalid should still be processed"
        assert received[0]["truck_id"] == "truck-after-invalid"

        await worker.stop()
        consumer_task.cancel()

    async def test_batch_produce_ordering(self):
        """Batch-produced messages should arrive in order (same partition key)."""
        from aiokafka import AIOKafkaProducer

        from apps.api.src.core.infrastructure.kafka.consumer import (
            KafkaConsumerWorker,
        )
        from apps.api.src.core.infrastructure.kafka.producer import (
            KafkaProducerHelper,
        )

        topic = f"test-batch-{uuid.uuid4().hex[:8]}"
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        worker = KafkaConsumerWorker(
            topics=[topic],
            group_id=f"test-group-{uuid.uuid4().hex[:8]}",
            handler=handler,
            bootstrap_servers="localhost:9092",
        )
        await worker.start()
        consumer_task = asyncio.create_task(worker.run())
        await asyncio.sleep(1)

        # Batch produce 10 messages
        raw_producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        producer = KafkaProducerHelper(raw_producer)
        await producer.start()

        batch = [{"seq": i, "truck_id": "truck-batch"} for i in range(10)]
        await producer.send_batch(topic=topic, values=batch, key_field="truck_id")
        await producer.stop()

        # Wait for all messages
        for _ in range(50):
            if len(received) >= 10:
                break
            await asyncio.sleep(0.1)

        assert len(received) == 10
        # Same partition key -> ordering preserved
        sequences = [msg["seq"] for msg in received]
        assert sequences == list(range(10)), f"Messages out of order: {sequences}"

        await worker.stop()
        consumer_task.cancel()
