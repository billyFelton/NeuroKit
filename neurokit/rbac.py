"""
RBAC enforcement for Neuro-Network services.

Provides a high-level interface for permission checking that combines
Vault RBAC lookups with audit logging. Used primarily by the Resolver
service, but available to any container that needs inline auth checks.
"""

import logging
from typing import Any, Dict, Optional

from neurokit.audit import AuditLogger
from neurokit.envelope import (
    AuthorizationContext,
    AuthorizationDecision,
    EventType,
    MessageEnvelope,
)
from neurokit.vault import VaultIAMClient, IAMAuthError, IAMNotFoundError

logger = logging.getLogger("neurokit.rbac")


class AccessDeniedError(Exception):
    """Raised when RBAC check fails and the request should not proceed."""

    def __init__(self, message: str, policy: Optional[str] = None):
        super().__init__(message)
        self.policy = policy


class RBACEnforcer:
    """
    Enforce role-based access control on message envelopes.

    Combines Vault permission checks with audit logging to provide
    a single-call authorization workflow.

    Usage:
        enforcer = RBACEnforcer(vault_client, audit_logger, "resolver")

        # Check and enrich — raises AccessDeniedError if denied
        try:
            enforcer.enforce(envelope, action="query", resource="wazuh-alerts")
        except AccessDeniedError as e:
            # Return denial response to user
            ...

        # Or check without raising
        result = enforcer.check(envelope, action="query", resource="wazuh-alerts")
        if not result.decision == AuthorizationDecision.PERMIT:
            ...
    """

    def __init__(
        self,
        vault: VaultIAMClient,
        audit: AuditLogger,
        service_name: str,
    ):
        self._vault = vault
        self._audit = audit
        self._service_name = service_name

    def check(
        self,
        envelope: MessageEnvelope,
        action: str,
        resource: str,
        resource_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AuthorizationContext:
        """
        Check permission and return the authorization context.

        Does NOT raise on denial. Updates the envelope's authorization context.
        Always logs the authorization decision.
        """
        user_id = envelope.actor.user_id

        if not user_id:
            auth_ctx = AuthorizationContext(
                decision=AuthorizationDecision.DENY,
                evaluated_by=self._service_name,
                denied_reason="No authenticated user identity on request",
            )
            envelope.authorization = auth_ctx
            self._log_decision(envelope, action, resource, auth_ctx)
            return auth_ctx

        try:
            result = self._vault.check_permission(
                user_id=user_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                context=context,
            )
        except IAMAuthError as e:
            auth_ctx = AuthorizationContext(
                decision=AuthorizationDecision.DENY,
                evaluated_by=self._service_name,
                denied_reason=f"Vault auth error: {e}",
            )
            envelope.authorization = auth_ctx
            self._log_decision(envelope, action, resource, auth_ctx)
            return auth_ctx
        except Exception as e:
            # Fail closed — deny on errors
            auth_ctx = AuthorizationContext(
                decision=AuthorizationDecision.DENY,
                evaluated_by=self._service_name,
                denied_reason=f"RBAC check failed: {e}",
            )
            envelope.authorization = auth_ctx
            self._log_decision(envelope, action, resource, auth_ctx)
            logger.error("RBAC check error for %s: %s", user_id, e, exc_info=True)
            return auth_ctx

        permitted = result.get("permitted", False)
        auth_ctx = AuthorizationContext(
            decision=AuthorizationDecision.PERMIT if permitted else AuthorizationDecision.DENY,
            policy_matched=result.get("policy_matched"),
            evaluated_by=self._service_name,
            scopes_granted=result.get("scopes_granted", []),
            denied_reason=result.get("denied_reason") if not permitted else None,
        )
        envelope.authorization = auth_ctx
        self._log_decision(envelope, action, resource, auth_ctx)
        return auth_ctx

    def enforce(
        self,
        envelope: MessageEnvelope,
        action: str,
        resource: str,
        resource_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AuthorizationContext:
        """
        Check permission and raise AccessDeniedError if denied.

        Use this when you want to gate processing on authorization.
        """
        auth_ctx = self.check(envelope, action, resource, resource_id, context)

        if auth_ctx.decision != AuthorizationDecision.PERMIT:
            raise AccessDeniedError(
                message=auth_ctx.denied_reason or "Access denied",
                policy=auth_ctx.policy_matched,
            )

        return auth_ctx

    def enrich_actor(self, envelope: MessageEnvelope) -> None:
        """
        Resolve and enrich the actor context on an envelope.

        Looks up the actor's full identity from Vault (roles, groups)
        based on whatever identity info is already on the envelope.
        Typically called by Resolver before RBAC checks.
        """
        actor = envelope.actor

        # Try to resolve from external ID if we don't have a canonical user_id
        if not actor.user_id and actor.source_channel and actor.source_channel_id:
            try:
                identity = self._vault.resolve_identity(
                    provider=actor.source_channel,
                    external_id=actor.source_channel_id,
                )
                actor.user_id = identity.get("user_id")
                actor.email = identity.get("email", actor.email)
                actor.display_name = identity.get("display_name", actor.display_name)
                actor.roles = identity.get("roles", [])
                actor.groups = identity.get("groups", [])
            except IAMNotFoundError:
                logger.warning(
                    "Cannot resolve identity for %s:%s",
                    actor.source_channel,
                    actor.source_channel_id,
                )
            except Exception as e:
                logger.error("Identity resolution failed: %s", e, exc_info=True)

        # If we have a user_id but no roles, fetch them
        elif actor.user_id and not actor.roles:
            try:
                actor.roles = self._vault.get_user_roles(actor.user_id)
                actor.groups = self._vault.get_user_groups(actor.user_id)
            except Exception as e:
                logger.error("Failed to fetch roles for %s: %s", actor.user_id, e)

    def _log_decision(
        self,
        envelope: MessageEnvelope,
        action: str,
        resource: str,
        auth_ctx: AuthorizationContext,
    ) -> None:
        """Log the authorization decision to audit."""
        self._audit.log_authorization(
            envelope=envelope,
            action=action,
            resource=resource,
            decision=auth_ctx.decision.value,
            policy_matched=auth_ctx.policy_matched,
            denied_reason=auth_ctx.denied_reason,
        )
