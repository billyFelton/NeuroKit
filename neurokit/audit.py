"""
Audit logger for SOC2-compliant event tracking.

Every container uses AuditLogger to emit structured audit events
to the centralized audit exchange. Vault consumes these events
and persists them with hash-chain tamper detection.
"""

import hashlib
import json
import logging
import threading
from typing import Any, Dict, Optional

from neurokit.config import NeuroConfig
from neurokit.envelope import (
    AuditEvent,
    AIInteractionContext,
    EventType,
    MessageEnvelope,
)

logger = logging.getLogger("neurokit.audit")


class AuditLogger:
    """
    Emit audit events for SOC2 compliance.

    Automatically handles:
    - Hash chaining for tamper detection
    - Prompt/response hashing vs full-text based on config
    - Publishing to the audit RabbitMQ exchange
    - Thread-safe hash chain maintenance

    Usage:
        config = NeuroConfig.from_env()
        rmq = RabbitMQClient(config)
        rmq.connect()
        audit = AuditLogger(config, rmq)

        # From a message envelope
        audit.log_from_envelope(
            envelope=msg,
            event_type=EventType.DATA_ACCESS,
            action="query_alerts",
            resource="wazuh-alerts",
            outcome_status="success",
            details={"alert_count": 15}
        )

        # System event (no user actor)
        audit.log_system(
            action="service_started",
            resource="connector-wazuh",
            details={"version": "1.0.0"}
        )

        # AI interaction
        audit.log_ai_interaction(
            envelope=msg,
            model="claude-sonnet-4-5-20250929",
            provider="anthropic",
            prompt_text="...",
            response_text="...",
            input_tokens=1500,
            output_tokens=800,
        )
    """

    def __init__(self, config: NeuroConfig, rabbitmq_client):
        """
        Args:
            config: NeuroKit configuration
            rabbitmq_client: Connected RabbitMQClient instance
        """
        self.config = config
        self.audit_config = config.audit
        self._rmq = rabbitmq_client
        self._last_hash: Optional[str] = None
        self._hash_lock = threading.Lock()

    def _compute_content_hash(self, content: str) -> str:
        """Hash content using configured algorithm."""
        algo = self.audit_config.hash_algorithm
        return hashlib.new(algo, content.encode()).hexdigest()

    def _chain_and_publish(self, event: AuditEvent) -> None:
        """Add to hash chain and publish to audit exchange."""
        if not self.audit_config.enabled:
            return

        with self._hash_lock:
            event.compute_hash(self._last_hash)
            self._last_hash = event.event_hash

        try:
            self._rmq.publish_audit(event.serialize())
            logger.debug("Audit event published: %s/%s", event.event_type.value, event.action)
        except Exception as e:
            # Audit failures should be logged but not crash the service
            logger.error("Failed to publish audit event: %s", e, exc_info=True)
            # TODO: Buffer to local file for later replay

    def log(self, event: AuditEvent) -> None:
        """Publish a pre-built audit event."""
        self._chain_and_publish(event)

    def log_from_envelope(
        self,
        envelope: MessageEnvelope,
        event_type: EventType,
        action: str,
        resource: str,
        outcome_status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        """Create and publish an audit event from a message envelope."""
        event = AuditEvent.from_envelope(
            envelope=envelope,
            event_type=event_type,
            action=action,
            resource=resource,
            outcome_status=outcome_status,
            details=details,
            resource_id=resource_id,
        )
        self._chain_and_publish(event)

    def log_system(
        self,
        action: str,
        resource: str = "",
        outcome_status: str = "success",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a system-level event (service start, config change, etc.)."""
        event = AuditEvent.system_event(
            source_service=self.config.service_name,
            action=action,
            resource=resource,
            outcome_status=outcome_status,
            details=details,
        )
        self._chain_and_publish(event)

    def log_ai_interaction(
        self,
        envelope: MessageEnvelope,
        model: str,
        provider: str,
        prompt_text: str,
        response_text: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        estimated_cost_usd: float = 0.0,
        request_id: Optional[str] = None,
        system_prompt_template: Optional[str] = None,
    ) -> None:
        """
        Log an AI model API call with appropriate data handling.

        Respects audit config for whether to store full prompt/response
        text or only hashes.
        """
        ai_ctx = AIInteractionContext(
            model=model,
            provider=provider,
            request_id=request_id,
            prompt_hash=self._compute_content_hash(prompt_text),
            response_hash=self._compute_content_hash(response_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            system_prompt_template=system_prompt_template,
        )

        # Only include full text if config allows it
        if self.audit_config.include_prompt_text:
            ai_ctx.prompt_text = prompt_text
        if self.audit_config.include_response_text:
            ai_ctx.response_text = response_text

        # Update envelope's AI context for downstream use
        envelope.ai_interaction = ai_ctx

        event = AuditEvent.from_envelope(
            envelope=envelope,
            event_type=EventType.AI_INTERACTION,
            action="ai_api_call",
            resource=f"{provider}/{model}",
            outcome_status="success",
            details={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "latency_ms": latency_ms,
                "estimated_cost_usd": estimated_cost_usd,
            },
        )
        event.ai_interaction = ai_ctx
        self._chain_and_publish(event)

    def log_authorization(
        self,
        envelope: MessageEnvelope,
        action: str,
        resource: str,
        decision: str,
        policy_matched: Optional[str] = None,
        denied_reason: Optional[str] = None,
    ) -> None:
        """Log an RBAC authorization decision."""
        event = AuditEvent.from_envelope(
            envelope=envelope,
            event_type=EventType.AUTHORIZATION,
            action=action,
            resource=resource,
            outcome_status="success" if decision == "permit" else "denied",
            details={
                "decision": decision,
                "policy_matched": policy_matched,
                "denied_reason": denied_reason,
            },
        )
        self._chain_and_publish(event)

    def log_authentication(
        self,
        envelope: MessageEnvelope,
        method: str,
        outcome: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an authentication event."""
        event = AuditEvent.from_envelope(
            envelope=envelope,
            event_type=EventType.AUTHENTICATION,
            action=f"auth_{method}",
            resource="identity",
            outcome_status=outcome,
            details=details,
        )
        self._chain_and_publish(event)
