"""
Vault-IAM client for identity resolution and RBAC queries.

This client talks to the Vault-IAM service, which owns:
- EntraID identity sync and user/group/role data
- Identity resolution (Slack user → EntraID → roles)
- RBAC policy evaluation

Secrets are handled separately by SecretsClient (HashiCorp Vault).
"""

import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from neurokit.config import NeuroConfig

logger = logging.getLogger("neurokit.vault_iam")


class IAMError(Exception):
    """Base exception for Vault-IAM operations."""
    pass


class IAMAuthError(IAMError):
    """Authentication/authorization failure."""
    pass


class IAMNotFoundError(IAMError):
    """Requested identity or resource not found."""
    pass


class VaultIAMClient:
    """
    Client for the Vault-IAM service.

    Handles identity resolution and RBAC queries against the
    centralized IAM database (Postgres iam schema).

    Usage:
        config = NeuroConfig.from_env()
        iam = VaultIAMClient(config)
        iam.authenticate(service_token="...")

        # Resolve identity
        identity = iam.resolve_identity(
            provider="slack",
            external_id="U12345ABC"
        )

        # Check permission
        result = iam.check_permission(
            user_id="entra-object-id",
            action="query",
            resource="wazuh-alerts"
        )

        # Get user details
        roles = iam.get_user_roles("entra-object-id")
    """

    def __init__(self, config: NeuroConfig):
        self.config = config
        self._iam_config = config.vault_iam
        self._base_url = self._iam_config.url.rstrip("/")

        self._session = requests.Session()
        retry_strategy = Retry(
            total=self._iam_config.retry_attempts,
            backoff_factor=self._iam_config.retry_delay,
            status_forcelist=[502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # Simple in-memory cache
        self._identity_cache: Dict[str, Dict] = {}
        self._role_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300  # 5 minutes

    def authenticate(self, service_token: Optional[str] = None) -> None:
        """
        Authenticate this service with Vault-IAM.

        Args:
            service_token: Service-to-service auth token
        """
        if service_token:
            self._session.headers["Authorization"] = f"Bearer {service_token}"
            logger.info("Authenticated with Vault-IAM using service token")
            return

        # Service-to-service auth via Vault-IAM's auth endpoint
        try:
            response = self._request("POST", "/api/v1/auth/service", json={
                "service_name": self.config.service_name,
                "service_version": self.config.service_version,
            })
            token = response["token"]
            self._session.headers["Authorization"] = f"Bearer {token}"
            logger.info("Authenticated with Vault-IAM as %s", self.config.service_name)
        except Exception as e:
            raise IAMAuthError(f"Failed to authenticate with Vault-IAM: {e}") from e

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make an HTTP request to Vault-IAM with error handling."""
        url = f"{self._base_url}{path}"
        kwargs.setdefault("timeout", self._iam_config.timeout)

        try:
            response = self._session.request(method, url, **kwargs)
        except requests.ConnectionError as e:
            raise IAMError(f"Cannot connect to Vault-IAM at {self._base_url}: {e}") from e
        except requests.Timeout as e:
            raise IAMError(f"Vault-IAM request timed out: {e}") from e

        if response.status_code == 401:
            raise IAMAuthError("Vault-IAM authentication failed")
        if response.status_code == 403:
            raise IAMAuthError(f"Vault-IAM permission denied for {method} {path}")
        if response.status_code == 404:
            raise IAMNotFoundError(f"Not found: {path}")
        if response.status_code >= 400:
            raise IAMError(f"Vault-IAM error {response.status_code}: {response.text}")

        return response.json()

    # ── Identity Resolution ─────────────────────────────────────────

    def resolve_identity(
        self,
        provider: str,
        external_id: str,
    ) -> Dict[str, Any]:
        """
        Map an external user ID to the canonical Neuro-Network identity.

        Args:
            provider: Identity source ("slack", "email", "entra", "teams")
            external_id: The ID from that provider (Slack user ID, email, etc.)

        Returns:
            Dict with user_id, email, display_name, roles, groups, status, etc.
        """
        cache_key = f"{provider}:{external_id}"
        cached = self._identity_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self._cache_ttl:
            return cached["identity"]

        result = self._request("GET", "/api/v1/identity/resolve", params={
            "provider": provider,
            "external_id": external_id,
        })

        identity = result["identity"]
        self._identity_cache[cache_key] = {"identity": identity, "ts": time.time()}
        logger.debug("Resolved %s:%s → %s", provider, external_id, identity.get("email"))
        return identity

    def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get full user profile by canonical user ID (EntraID object ID)."""
        return self._request("GET", f"/api/v1/identity/{user_id}")

    def get_user_roles(self, user_id: str) -> List[str]:
        """Get all roles assigned to a user."""
        cache_key = f"roles:{user_id}"
        cached = self._role_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self._cache_ttl:
            return cached["roles"]

        result = self._request("GET", f"/api/v1/identity/{user_id}/roles")
        roles = result.get("roles", [])
        self._role_cache[cache_key] = {"roles": roles, "ts": time.time()}
        return roles

    def get_user_groups(self, user_id: str) -> List[str]:
        """Get all groups a user belongs to (synced from EntraID)."""
        result = self._request("GET", f"/api/v1/identity/{user_id}/groups")
        return result.get("groups", [])

    # ── RBAC Permission Checks ──────────────────────────────────────

    def check_permission(
        self,
        user_id: str,
        action: str,
        resource: str,
        resource_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check if a user is authorized to perform an action on a resource.

        Args:
            user_id: EntraID object ID
            action: The action (e.g., "query", "modify", "delete", "view")
            resource: The resource type (e.g., "wazuh-alerts", "entra-signin-logs")
            resource_id: Optional specific resource instance
            context: Additional context for policy evaluation

        Returns:
            Dict with:
                - permitted (bool)
                - policy_matched (str or None)
                - scopes_granted (list of str)
                - denied_reason (str or None)
        """
        return self._request("POST", "/api/v1/rbac/check", json={
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "context": context or {},
        })

    def check_permission_bool(
        self,
        user_id: str,
        action: str,
        resource: str,
    ) -> bool:
        """Simple boolean permission check."""
        result = self.check_permission(user_id, action, resource)
        return result.get("permitted", False)

    # ── Audit Log Query (via Vault-Audit, proxied through IAM) ──────

    def query_audit_logs(
        self,
        filters: Optional[Dict[str, Any]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Query audit logs (requires security-admin role).

        Proxied through Vault-IAM which enforces RBAC before
        forwarding to Vault-Audit.
        """
        return self._request("POST", "/api/v1/audit/query", json={
            "filters": filters or {},
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
            "offset": offset,
        })

    # ── Cache Management ────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear all cached identities and roles."""
        self._identity_cache.clear()
        self._role_cache.clear()
        logger.info("Vault-IAM cache cleared")

    def invalidate_identity(self, provider: str, external_id: str) -> None:
        """Invalidate a specific cached identity."""
        cache_key = f"{provider}:{external_id}"
        self._identity_cache.pop(cache_key, None)

    def invalidate_roles(self, user_id: str) -> None:
        """Invalidate cached roles for a user."""
        self._role_cache.pop(f"roles:{user_id}", None)
