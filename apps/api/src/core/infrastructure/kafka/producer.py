"""Domain-agnostic Kafka producer helper.

Wraps aiokafka.AIOKafkaProducer with JSON serialization
and a clean async interface. Any domain can use this to
publish events to Kafka topics.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KafkaProducerHelper:
    """Thin wrapper over an aiokafka producer with JSON serialization."""

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def start(self) -> None:
        """Start the underlying Kafka producer."""
        await self._producer.start()

    async def stop(self) -> None:
        """Stop the underlying Kafka producer."""
        await self._producer.stop()

    async def send(
        self,
        topic: str,
        value: dict[str, Any],
        key: str | None = None,
    ) -> None:
        """Send a single JSON message to a Kafka topic.

        Args:
            topic: Kafka topic name.
            value: Dict to JSON-serialize as the message value.
            key: Optional partition key (string, will be UTF-8 encoded).
        """
        value_bytes = json.dumps(value, default=str).encode("utf-8")
        key_bytes = key.encode("utf-8") if key else None

        await self._producer.send_and_wait(
            topic=topic,
            value=value_bytes,
            key=key_bytes,
        )

    async def send_batch(
        self,
        topic: str,
        values: list[dict[str, Any]],
        key_field: str | None = None,
    ) -> None:
        """Send multiple messages to a Kafka topic.

        Args:
            topic: Kafka topic name.
            values: List of dicts to send.
            key_field: Optional field name to use as partition key from each dict.
        """
        for value in values:
            key = str(value[key_field]) if key_field and key_field in value else None
            await self.send(topic=topic, value=value, key=key)
