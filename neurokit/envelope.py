"""
Standardized message envelopes for the Neuro-Network.

Every message flowing through RabbitMQ uses these structures to ensure
consistent routing, audit trails, and RBAC enforcement.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    """Categories of audit events for SOC2 compliance."""
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    AI_INTERACTION = "ai_interaction"
    SYSTEM_EVENT = "system_event"
    CONFIGURATION_CHANGE = "configuration_change"
    SERVICE_LIFECYCLE = "service_lifecycle"
    ERROR = "error"


class AuthorizationDecision(str, Enum):
    PERMIT = "permit"
    DENY = "deny"
    NOT_EVALUATED = "not_evaluated"


@dataclass
class ActorContext:
    """Identifies who initiated the action."""
    user_id: Optional[str] = None           # EntraID object ID
    email: Optional[str] = None
    display_name: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    source_channel: Optional[str] = None    # slack, email, api, system
    source_channel_id: Optional[str] = None # Slack channel ID, email thread ID, etc.
    ip_address: Optional[str] = None
    is_service_account: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuthorizationContext:
    """Records the RBAC decision for this request."""
    decision: AuthorizationDecision = AuthorizationDecision.NOT_EVALUATED
    policy_matched: Optional[str] = None
    evaluated_by: Optional[str] = None  # service name that made the decision
    evaluated_at: Optional[str] = None
    denied_reason: Optional[str] = None
    scopes_granted: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["decision"] = self.decision.value
        return result


@dataclass
class AIInteractionContext:
    """Tracks AI model usage for audit and cost tracking."""
    model: Optional[str] = None             # claude-sonnet-4-5-20250929, grok-2, etc.
    provider: Optional[str] = None          # anthropic, xai, openai
    request_id: Optional[str] = None        # Provider's request ID
    prompt_hash: Optional[str] = None       # SHA256 of full prompt
    response_hash: Optional[str] = None     # SHA256 of full response
    prompt_text: Optional[str] = None       # Only if audit config allows
    response_text: Optional[str] = None     # Only if audit config allows
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    system_prompt_template: Optional[str] = None  # Template name used

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != 0}


@dataclass
class MessageEnvelope:
    """
    Standard message format for all RabbitMQ communication.

    Every message in the Neuro-Network is wrapped in this envelope to ensure
    consistent routing, traceability, and audit compliance.

    Usage:
        # Creating a new message
        envelope = MessageEnvelope.create(
            source="connector-slack",
            message_type="user.query",
            payload={"text": "What are today's critical alerts?"},
            actor=ActorContext(
                user_id="entra-obj-id",
                email="jane@company.com",
                roles=["security-analyst"],
                source_channel="slack"
            )
        )

        # Serialize for RabbitMQ
        body = envelope.serialize()

        # Deserialize on receipt
        envelope = MessageEnvelope.deserialize(body)
    """

    # Identity & routing
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None    # Links related messages in a flow
    causation_id: Optional[str] = None      # The message that caused this one
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Source & destination
    source_service: str = ""
    target_service: Optional[str] = None    # None = routed by exchange/queue binding
    message_type: str = ""                  # e.g., "user.query", "alert.wazuh", "auth.check"

    # Content
    payload: Dict[str, Any] = field(default_factory=dict)

    # Context (enriched as message flows through the network)
    actor: ActorContext = field(default_factory=ActorContext)
    authorization: AuthorizationContext = field(default_factory=AuthorizationContext)
    ai_interaction: AIInteractionContext = field(default_factory=AIInteractionContext)

    # Routing metadata
    reply_to: Optional[str] = None          # Queue to send response to
    ttl: Optional[int] = None               # Time-to-live in seconds
    priority: int = 5                       # 1 (lowest) to 10 (highest)
    retry_count: int = 0
    max_retries: int = 3

    @classmethod
    def create(
        cls,
        source: str,
        message_type: str,
        payload: Dict[str, Any],
        actor: Optional[ActorContext] = None,
        correlation_id: Optional[str] = None,
        priority: int = 5,
        reply_to: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> "MessageEnvelope":
        """Factory method to create a new envelope with proper defaults."""
        envelope = cls(
            source_service=source,
            message_type=message_type,
            payload=payload,
            priority=priority,
            reply_to=reply_to,
            ttl=ttl,
        )
        if actor:
            envelope.actor = actor
        if correlation_id:
            envelope.correlation_id = correlation_id
        else:
            envelope.correlation_id = envelope.message_id
        return envelope

    def create_reply(
        self,
        source: str,
        message_type: str,
        payload: Dict[str, Any],
    ) -> "MessageEnvelope":
        """Create a reply envelope that preserves correlation chain."""
        return MessageEnvelope.create(
            source=source,
            message_type=message_type,
            payload=payload,
            actor=self.actor,
            correlation_id=self.correlation_id,
            reply_to=None,
        )

    def create_child(
        self,
        source: str,
        message_type: str,
        payload: Dict[str, Any],
    ) -> "MessageEnvelope":
        """Create a child message (sub-request) that tracks causation."""
        child = MessageEnvelope.create(
            source=source,
            message_type=message_type,
            payload=payload,
            actor=self.actor,
            correlation_id=self.correlation_id,
        )
        child.causation_id = self.message_id
        child.authorization = self.authorization
        return child

    def serialize(self) -> bytes:
        """Serialize to JSON bytes for RabbitMQ publishing."""
        data = {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp,
            "source_service": self.source_service,
            "target_service": self.target_service,
            "message_type": self.message_type,
            "payload": self.payload,
            "actor": self.actor.to_dict(),
            "authorization": self.authorization.to_dict(),
            "ai_interaction": self.ai_interaction.to_dict(),
            "reply_to": self.reply_to,
            "ttl": self.ttl,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }
        return json.dumps(data, default=str).encode("utf-8")

    @classmethod
    def deserialize(cls, body: bytes) -> "MessageEnvelope":
        """Deserialize from RabbitMQ message body."""
        data = json.loads(body.decode("utf-8"))

        actor_data = data.pop("actor", {})
        auth_data = data.pop("authorization", {})
        ai_data = data.pop("ai_interaction", {})

        # Reconstruct enum values
        if "decision" in auth_data and isinstance(auth_data["decision"], str):
            auth_data["decision"] = AuthorizationDecision(auth_data["decision"])

        envelope = cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })
        envelope.actor = ActorContext(**actor_data)
        envelope.authorization = AuthorizationContext(**auth_data)
        envelope.ai_interaction = AIInteractionContext(**ai_data)
        return envelope

    def payload_hash(self) -> str:
        """SHA256 hash of the payload for audit purposes."""
        content = json.dumps(self.payload, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class AuditEvent:
    """
    Dedicated audit event structure for SOC2 compliance.

    Every service publishes these to the audit exchange. Vault consumes
    and persists them in the append-only audit store.

    Usage:
        event = AuditEvent.from_envelope(
            envelope=msg,
            event_type=EventType.DATA_ACCESS,
            action="query_alerts",
            resource="wazuh-alerts",
            outcome_status="success",
            details={"alert_count": 15}
        )
        audit_logger.log(event)
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_service: str = ""
    event_type: EventType = EventType.SYSTEM_EVENT

    # Who
    actor: ActorContext = field(default_factory=ActorContext)

    # What
    action: str = ""
    resource: str = ""
    resource_id: Optional[str] = None

    # Authorization
    authorization: AuthorizationContext = field(default_factory=AuthorizationContext)

    # AI-specific (populated for AI interactions)
    ai_interaction: Optional[AIInteractionContext] = None

    # Outcome
    outcome_status: str = "success"  # success, failure, error, denied
    outcome_details: Dict[str, Any] = field(default_factory=dict)

    # Traceability
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    message_id: Optional[str] = None

    # Hash chain for tamper detection
    previous_event_hash: Optional[str] = None
    event_hash: Optional[str] = None

    @classmethod
    def from_envelope(
        cls,
        envelope: MessageEnvelope,
        event_type: EventType,
        action: str,
        resource: str,
        outcome_status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        resource_id: Optional[str] = None,
    ) -> "AuditEvent":
        """Create an audit event from a message envelope, preserving full context."""
        event = cls(
            source_service=envelope.source_service,
            event_type=event_type,
            actor=envelope.actor,
            action=action,
            resource=resource,
            resource_id=resource_id,
            authorization=envelope.authorization,
            outcome_status=outcome_status,
            outcome_details=details or {},
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            message_id=envelope.message_id,
        )
        if envelope.ai_interaction and envelope.ai_interaction.model:
            event.ai_interaction = envelope.ai_interaction
        return event

    @classmethod
    def system_event(
        cls,
        source_service: str,
        action: str,
        resource: str = "",
        outcome_status: str = "success",
        details: Optional[Dict[str, Any]] = None,
    ) -> "AuditEvent":
        """Create a system-level audit event (no user actor)."""
        return cls(
            source_service=source_service,
            event_type=EventType.SYSTEM_EVENT,
            actor=ActorContext(is_service_account=True),
            action=action,
            resource=resource,
            outcome_status=outcome_status,
            outcome_details=details or {},
        )

    def compute_hash(self, previous_hash: Optional[str] = None) -> str:
        """Compute hash for tamper detection chain."""
        self.previous_event_hash = previous_hash
        content = json.dumps({
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "source_service": self.source_service,
            "event_type": self.event_type.value,
            "action": self.action,
            "resource": self.resource,
            "outcome_status": self.outcome_status,
            "previous_hash": previous_hash,
        }, sort_keys=True)
        self.event_hash = hashlib.sha256(content.encode()).hexdigest()
        return self.event_hash

    def serialize(self) -> bytes:
        """Serialize for publishing to audit exchange."""
        data = asdict(self)
        data["event_type"] = self.event_type.value
        if self.authorization:
            data["authorization"]["decision"] = self.authorization.decision.value
        return json.dumps(data, default=str).encode("utf-8")

    @classmethod
    def deserialize(cls, body: bytes) -> "AuditEvent":
        """Deserialize from audit exchange message."""
        data = json.loads(body.decode("utf-8"))
        data["event_type"] = EventType(data["event_type"])

        actor_data = data.pop("actor", {})
        auth_data = data.pop("authorization", {})
        ai_data = data.pop("ai_interaction", None)

        if "decision" in auth_data and isinstance(auth_data["decision"], str):
            auth_data["decision"] = AuthorizationDecision(auth_data["decision"])

        event = cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })
        event.actor = ActorContext(**actor_data)
        event.authorization = AuthorizationContext(**auth_data)
        if ai_data:
            event.ai_interaction = AIInteractionContext(**ai_data)
        return event
