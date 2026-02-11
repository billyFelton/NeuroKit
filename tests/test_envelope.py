"""Tests for MessageEnvelope and AuditEvent serialization."""

import json
import pytest

from neurokit.envelope import (
    ActorContext,
    AIInteractionContext,
    AuditEvent,
    AuthorizationContext,
    AuthorizationDecision,
    EventType,
    MessageEnvelope,
)


class TestMessageEnvelope:
    """Test MessageEnvelope creation, serialization, and deserialization."""

    def test_create_basic(self):
        envelope = MessageEnvelope.create(
            source="test-service",
            message_type="test.query",
            payload={"text": "hello"},
        )
        assert envelope.source_service == "test-service"
        assert envelope.message_type == "test.query"
        assert envelope.payload == {"text": "hello"}
        assert envelope.message_id is not None
        assert envelope.correlation_id == envelope.message_id

    def test_create_with_actor(self):
        actor = ActorContext(
            user_id="user-123",
            email="jane@company.com",
            roles=["security-analyst"],
            source_channel="slack",
        )
        envelope = MessageEnvelope.create(
            source="connector-slack",
            message_type="user.query",
            payload={"text": "show alerts"},
            actor=actor,
        )
        assert envelope.actor.email == "jane@company.com"
        assert "security-analyst" in envelope.actor.roles

    def test_serialize_deserialize_roundtrip(self):
        actor = ActorContext(
            user_id="user-123",
            email="jane@company.com",
            roles=["security-analyst", "it-support"],
            groups=["SOC-Team"],
            source_channel="slack",
            source_channel_id="U12345",
        )
        envelope = MessageEnvelope.create(
            source="test",
            message_type="test.roundtrip",
            payload={"key": "value", "nested": {"a": 1}},
            actor=actor,
            priority=8,
        )
        envelope.authorization = AuthorizationContext(
            decision=AuthorizationDecision.PERMIT,
            policy_matched="test-policy",
            evaluated_by="resolver",
            scopes_granted=["read"],
        )

        serialized = envelope.serialize()
        restored = MessageEnvelope.deserialize(serialized)

        assert restored.message_id == envelope.message_id
        assert restored.correlation_id == envelope.correlation_id
        assert restored.source_service == "test"
        assert restored.message_type == "test.roundtrip"
        assert restored.payload == {"key": "value", "nested": {"a": 1}}
        assert restored.actor.email == "jane@company.com"
        assert restored.actor.roles == ["security-analyst", "it-support"]
        assert restored.authorization.decision == AuthorizationDecision.PERMIT
        assert restored.authorization.policy_matched == "test-policy"
        assert restored.priority == 8

    def test_create_reply(self):
        original = MessageEnvelope.create(
            source="connector-slack",
            message_type="user.query",
            payload={"text": "hello"},
            actor=ActorContext(user_id="u1", email="test@test.com"),
        )
        reply = original.create_reply(
            source="agent-worker-claude",
            message_type="ai.response",
            payload={"text": "response"},
        )
        assert reply.correlation_id == original.correlation_id
        assert reply.source_service == "agent-worker-claude"
        assert reply.actor.email == "test@test.com"

    def test_create_child(self):
        parent = MessageEnvelope.create(
            source="agent-worker",
            message_type="ai.request",
            payload={},
        )
        child = parent.create_child(
            source="agent-worker",
            message_type="wazuh.query",
            payload={"level": "critical"},
        )
        assert child.correlation_id == parent.correlation_id
        assert child.causation_id == parent.message_id
        assert child.message_id != parent.message_id

    def test_payload_hash_deterministic(self):
        e1 = MessageEnvelope.create(
            source="test", message_type="test", payload={"a": 1, "b": 2}
        )
        e2 = MessageEnvelope.create(
            source="test", message_type="test", payload={"b": 2, "a": 1}
        )
        assert e1.payload_hash() == e2.payload_hash()


class TestAuditEvent:
    """Test AuditEvent creation and hash chain."""

    def test_from_envelope(self):
        envelope = MessageEnvelope.create(
            source="connector-wazuh",
            message_type="wazuh.query",
            payload={"level": "critical"},
            actor=ActorContext(user_id="u1", email="analyst@co.com", roles=["security-analyst"]),
        )
        event = AuditEvent.from_envelope(
            envelope=envelope,
            event_type=EventType.DATA_ACCESS,
            action="query_alerts",
            resource="wazuh-alerts",
            outcome_status="success",
            details={"alert_count": 15},
        )
        assert event.source_service == "connector-wazuh"
        assert event.event_type == EventType.DATA_ACCESS
        assert event.action == "query_alerts"
        assert event.actor.email == "analyst@co.com"
        assert event.outcome_details == {"alert_count": 15}
        assert event.correlation_id == envelope.correlation_id

    def test_system_event(self):
        event = AuditEvent.system_event(
            source_service="conductor",
            action="service_started",
            resource="connector-wazuh",
            details={"version": "1.0.0"},
        )
        assert event.actor.is_service_account is True
        assert event.event_type == EventType.SYSTEM_EVENT

    def test_hash_chain(self):
        e1 = AuditEvent.system_event("test", "action1")
        hash1 = e1.compute_hash(previous_hash=None)
        assert e1.previous_event_hash is None
        assert e1.event_hash == hash1

        e2 = AuditEvent.system_event("test", "action2")
        hash2 = e2.compute_hash(previous_hash=hash1)
        assert e2.previous_event_hash == hash1
        assert e2.event_hash != hash1

        e3 = AuditEvent.system_event("test", "action3")
        hash3 = e3.compute_hash(previous_hash=hash2)
        assert e3.previous_event_hash == hash2

    def test_serialize_deserialize(self):
        event = AuditEvent.from_envelope(
            envelope=MessageEnvelope.create("test", "test", {}),
            event_type=EventType.AI_INTERACTION,
            action="ai_api_call",
            resource="anthropic/claude-sonnet",
        )
        event.ai_interaction = AIInteractionContext(
            model="claude-sonnet-4-5-20250929",
            provider="anthropic",
            input_tokens=100,
            output_tokens=200,
        )
        event.compute_hash(None)

        serialized = event.serialize()
        restored = AuditEvent.deserialize(serialized)

        assert restored.event_id == event.event_id
        assert restored.event_type == EventType.AI_INTERACTION
        assert restored.ai_interaction.model == "claude-sonnet-4-5-20250929"
        assert restored.event_hash == event.event_hash


class TestActorContext:
    """Test ActorContext serialization."""

    def test_to_dict(self):
        actor = ActorContext(
            user_id="uid",
            email="test@test.com",
            display_name="Test User",
            roles=["admin"],
            groups=["SOC"],
            source_channel="slack",
            source_channel_id="U123",
            is_service_account=False,
        )
        d = actor.to_dict()
        assert d["email"] == "test@test.com"
        assert d["roles"] == ["admin"]
        assert d["is_service_account"] is False
