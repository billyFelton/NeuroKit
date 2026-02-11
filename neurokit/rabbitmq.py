"""
RabbitMQ client for the Neuro-Network.

Provides connection management, channel pooling, and standardized
publishing/consuming with automatic audit event emission.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel

from neurokit.config import NeuroConfig, RabbitMQConfig
from neurokit.envelope import MessageEnvelope

logger = logging.getLogger("neurokit.rabbitmq")


class RabbitMQClient:
    """
    Managed RabbitMQ connection for Neuro-Network services.

    Handles connection lifecycle, exchange/queue declarations, and provides
    standardized publish/consume methods using MessageEnvelope format.

    Usage:
        config = NeuroConfig.from_env()
        rmq = RabbitMQClient(config)
        rmq.connect()

        # Publish
        rmq.publish("user.query", envelope)

        # Consume
        rmq.consume("connector-wazuh.inbox", handler_callback)

        # Cleanup
        rmq.disconnect()
    """

    # Standard queue naming convention
    QUEUE_PREFIX = "neuro"

    def __init__(self, config: NeuroConfig):
        self.config = config
        self.rmq_config: RabbitMQConfig = config.rabbitmq
        self._connection: Optional[pika.BlockingConnection] = None
        self._operational_channel: Optional[BlockingChannel] = None
        self._audit_channel: Optional[BlockingChannel] = None
        self._consuming = False

    def connect(self) -> None:
        """Establish connection and set up channels and exchanges."""
        credentials = pika.PlainCredentials(
            self.rmq_config.username,
            self.rmq_config.password,
        )
        parameters = pika.ConnectionParameters(
            host=self.rmq_config.host,
            port=self.rmq_config.port,
            virtual_host=self.rmq_config.vhost,
            credentials=credentials,
            heartbeat=self.rmq_config.heartbeat,
            connection_attempts=self.rmq_config.connection_attempts,
            retry_delay=self.rmq_config.retry_delay,
        )

        for attempt in range(1, self.rmq_config.connection_attempts + 1):
            try:
                self._connection = pika.BlockingConnection(parameters)
                self._operational_channel = self._connection.channel()
                self._audit_channel = self._connection.channel()

                self._operational_channel.basic_qos(
                    prefetch_count=self.rmq_config.prefetch_count
                )

                self._declare_topology()

                logger.info(
                    "Connected to RabbitMQ at %s:%s (attempt %d)",
                    self.rmq_config.host,
                    self.rmq_config.port,
                    attempt,
                )
                return

            except pika.exceptions.AMQPConnectionError as e:
                logger.warning(
                    "RabbitMQ connection attempt %d/%d failed: %s",
                    attempt,
                    self.rmq_config.connection_attempts,
                    e,
                )
                if attempt < self.rmq_config.connection_attempts:
                    time.sleep(self.rmq_config.retry_delay)
                else:
                    raise ConnectionError(
                        f"Failed to connect to RabbitMQ after "
                        f"{self.rmq_config.connection_attempts} attempts"
                    ) from e

    def _declare_topology(self) -> None:
        """Declare exchanges and dead-letter infrastructure."""
        # Operational topic exchange — all service-to-service messages
        self._operational_channel.exchange_declare(
            exchange=self.rmq_config.operational_exchange,
            exchange_type="topic",
            durable=True,
        )

        # Audit fanout exchange — all audit events go to Vault
        self._audit_channel.exchange_declare(
            exchange=self.rmq_config.audit_exchange,
            exchange_type="fanout",
            durable=True,
        )

        # Dead letter exchange for failed messages
        self._operational_channel.exchange_declare(
            exchange=self.rmq_config.dead_letter_exchange,
            exchange_type="topic",
            durable=True,
        )

        logger.info("RabbitMQ topology declared")

    def declare_queue(
        self,
        queue_name: str,
        routing_keys: list[str],
        durable: bool = True,
        ttl: Optional[int] = None,
    ) -> str:
        """
        Declare a queue bound to the operational exchange with routing keys.

        Args:
            queue_name: Queue name (will be prefixed with QUEUE_PREFIX)
            routing_keys: List of routing key patterns to bind (e.g., ["user.query", "alert.*"])
            durable: Whether queue survives broker restart
            ttl: Message TTL in milliseconds

        Returns:
            Full queue name
        """
        full_name = f"{self.QUEUE_PREFIX}.{queue_name}"
        arguments: Dict[str, Any] = {
            "x-dead-letter-exchange": self.rmq_config.dead_letter_exchange,
            "x-dead-letter-routing-key": f"dlx.{queue_name}",
        }
        if ttl:
            arguments["x-message-ttl"] = ttl

        self._operational_channel.queue_declare(
            queue=full_name,
            durable=durable,
            arguments=arguments,
        )

        for key in routing_keys:
            self._operational_channel.queue_bind(
                queue=full_name,
                exchange=self.rmq_config.operational_exchange,
                routing_key=key,
            )

        # Also declare matching DLX queue
        dlx_queue = f"{self.QUEUE_PREFIX}.dlx.{queue_name}"
        self._operational_channel.queue_declare(queue=dlx_queue, durable=True)
        self._operational_channel.queue_bind(
            queue=dlx_queue,
            exchange=self.rmq_config.dead_letter_exchange,
            routing_key=f"dlx.{queue_name}",
        )

        logger.info("Declared queue %s with bindings %s", full_name, routing_keys)
        return full_name

    def declare_audit_queue(self, queue_name: str = "vault.audit") -> str:
        """Declare the audit consumer queue (typically only Vault does this)."""
        full_name = f"{self.QUEUE_PREFIX}.{queue_name}"
        self._audit_channel.queue_declare(queue=full_name, durable=True)
        self._audit_channel.queue_bind(
            queue=full_name,
            exchange=self.rmq_config.audit_exchange,
        )
        logger.info("Declared audit queue %s", full_name)
        return full_name

    def publish(
        self,
        routing_key: str,
        envelope: MessageEnvelope,
    ) -> None:
        """
        Publish a message to the operational exchange.

        Args:
            routing_key: Topic routing key (e.g., "user.query", "alert.wazuh.critical")
            envelope: The message envelope to publish
        """
        if not self._operational_channel or self._operational_channel.is_closed:
            raise ConnectionError("Not connected to RabbitMQ")

        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # Persistent
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            reply_to=envelope.reply_to,
            priority=envelope.priority,
            headers={
                "source_service": envelope.source_service,
                "message_type": envelope.message_type,
            },
        )

        if envelope.ttl:
            properties.expiration = str(envelope.ttl * 1000)

        self._operational_channel.basic_publish(
            exchange=self.rmq_config.operational_exchange,
            routing_key=routing_key,
            body=envelope.serialize(),
            properties=properties,
        )

        logger.debug(
            "Published %s to %s (id=%s, corr=%s)",
            envelope.message_type,
            routing_key,
            envelope.message_id,
            envelope.correlation_id,
        )

    def publish_audit(self, audit_event_body: bytes) -> None:
        """
        Publish an audit event to the audit exchange.

        This is called by AuditLogger, not directly by services.
        """
        if not self._audit_channel or self._audit_channel.is_closed:
            raise ConnectionError("Not connected to RabbitMQ (audit channel)")

        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # Persistent — audit events must survive restarts
        )

        self._audit_channel.basic_publish(
            exchange=self.rmq_config.audit_exchange,
            routing_key="",  # Fanout exchange ignores routing key
            body=audit_event_body,
            properties=properties,
        )

    def consume(
        self,
        queue_name: str,
        callback: Callable[[MessageEnvelope], Optional[MessageEnvelope]],
        auto_ack: bool = False,
    ) -> None:
        """
        Start consuming from a queue with automatic envelope deserialization.

        The callback receives a deserialized MessageEnvelope and optionally
        returns a response envelope to be published to the reply_to queue.

        Args:
            queue_name: Full queue name (as returned by declare_queue)
            callback: Handler function
            auto_ack: Whether to auto-acknowledge messages
        """
        def _wrapped_callback(ch, method, properties, body):
            try:
                envelope = MessageEnvelope.deserialize(body)
                logger.debug(
                    "Received %s from %s (id=%s)",
                    envelope.message_type,
                    envelope.source_service,
                    envelope.message_id,
                )

                result = callback(envelope)

                # If handler returns a response and there's a reply_to, publish it
                if result and envelope.reply_to:
                    self.publish(envelope.reply_to, result)

                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as e:
                logger.error(
                    "Error processing message %s: %s",
                    getattr(envelope, "message_id", "unknown"),
                    e,
                    exc_info=True,
                )
                if not auto_ack:
                    # Reject and send to DLX if retries exhausted
                    try:
                        envelope_obj = MessageEnvelope.deserialize(body)
                        if envelope_obj.retry_count >= envelope_obj.max_retries:
                            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                        else:
                            envelope_obj.retry_count += 1
                            self.publish(method.routing_key, envelope_obj)
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                    except Exception:
                        ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

        self._operational_channel.basic_consume(
            queue=queue_name,
            on_message_callback=_wrapped_callback,
            auto_ack=auto_ack,
        )
        self._consuming = True
        logger.info("Consuming from %s", queue_name)

    def start_consuming(self) -> None:
        """Block and process messages. Call after setting up consumers."""
        if not self._consuming:
            raise RuntimeError("No consumers registered. Call consume() first.")
        logger.info("Starting message consumption loop")
        self._operational_channel.start_consuming()

    def stop_consuming(self) -> None:
        """Stop the consumption loop."""
        if self._operational_channel and not self._operational_channel.is_closed:
            self._operational_channel.stop_consuming()
        self._consuming = False

    def disconnect(self) -> None:
        """Close all channels and the connection."""
        self.stop_consuming()
        if self._connection and not self._connection.is_closed:
            self._connection.close()
            logger.info("Disconnected from RabbitMQ")

    @property
    def is_connected(self) -> bool:
        return (
            self._connection is not None
            and not self._connection.is_closed
        )
