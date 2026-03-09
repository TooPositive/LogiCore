"""Domain-agnostic Kafka consumer worker.

Provides a base consumer that deserializes JSON messages and
dispatches them to a handler coroutine. Tracks health metrics
(message count, errors, last message timestamp) for monitoring.

Any domain can subclass or instantiate this with their own handler.
"""

import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class KafkaConsumerWorker:
    """Async Kafka consumer with JSON deserialization and health tracking.

    Args:
        topics: List of Kafka topics to subscribe to.
        group_id: Consumer group ID.
        handler: Async function to process each deserialized message.
        bootstrap_servers: Kafka bootstrap servers.
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        bootstrap_servers: str = "localhost:9092",
    ) -> None:
        self.topics = topics
        self.group_id = group_id
        self._handler = handler
        self._bootstrap_servers = bootstrap_servers

        # Health metrics
        self.messages_processed: int = 0
        self.errors: int = 0
        self.last_message_at: datetime | None = None
        self._running: bool = False
        self._consumer: Any = None

    @property
    def is_healthy(self) -> bool:
        """Whether the consumer is running and processing messages."""
        return self._running

    async def start(self) -> None:
        """Start the Kafka consumer and begin processing messages."""
        from aiokafka import AIOKafkaConsumer

        self._consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda v: v,  # raw bytes, we deserialize ourselves
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Kafka consumer started: topics=%s group=%s",
            self.topics,
            self.group_id,
        )

    async def stop(self) -> None:
        """Stop the Kafka consumer gracefully."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped: group=%s", self.group_id)

    async def run(self) -> None:
        """Main consumer loop -- fetches and processes messages.

        Call start() before run(). Runs until stop() is called.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        async for msg in self._consumer:
            if not self._running:
                break
            await self._process_message(msg)

    async def _process_message(self, msg: Any) -> None:
        """Deserialize and dispatch a single Kafka message.

        Handles JSON deserialization errors and handler exceptions
        without crashing the consumer loop.
        """
        try:
            data = json.loads(msg.value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.error(
                "Invalid JSON on topic=%s partition=%s offset=%s",
                msg.topic,
                msg.partition,
                msg.offset,
            )
            self.errors += 1
            return

        try:
            await self._handler(data)
            self.messages_processed += 1
            self.last_message_at = datetime.now(UTC)
        except Exception:
            logger.exception(
                "Handler error on topic=%s partition=%s offset=%s",
                msg.topic,
                msg.partition,
                msg.offset,
            )
            self.errors += 1
