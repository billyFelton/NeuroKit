"""
HashiCorp Vault client for secrets management.

Handles AppRole authentication, secret retrieval, and lease renewal.
Each container authenticates directly with HashiCorp Vault using its
own AppRole credentials, scoped to only the secrets it needs.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import hvac
import hvac.exceptions

from neurokit.config import NeuroConfig

logger = logging.getLogger("neurokit.secrets")


class SecretsError(Exception):
    """Base exception for secrets operations."""
    pass


class SecretsAuthError(SecretsError):
    """AppRole authentication failed."""
    pass


class SecretsClient:
    """
    Client for HashiCorp Vault secret retrieval.

    Each Neuro-Network container authenticates via AppRole and can
    only access secrets scoped to its role policy.

    Usage:
        config = NeuroConfig.from_env()
        secrets = SecretsClient(config)
        secrets.authenticate()

        # Get a static secret
        api_key = secrets.get("anthropic/api_key")

        # Get all secrets at a path
        wazuh_creds = secrets.get_all("wazuh")

        # Dynamic secrets (e.g., database credentials)
        db_creds = secrets.get_dynamic("database/creds/vault-iam")
    """

    # Secrets engine mount points
    STATIC_MOUNT = "neuro-secrets"   # KV v2 engine
    DYNAMIC_MOUNT = "neuro-dynamic"  # Database / other dynamic engines

    def __init__(self, config: NeuroConfig):
        self.config = config
        self._hv_config = config.hashicorp_vault

        self._client: Optional[hvac.Client] = None
        self._token: Optional[str] = None
        self._lease_id: Optional[str] = None
        self._renewal_thread: Optional[threading.Thread] = None
        self._renewal_running = False

        # Local cache to avoid hammering Vault on hot paths
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes

    def authenticate(
        self,
        role_id: Optional[str] = None,
        secret_id: Optional[str] = None,
    ) -> None:
        """
        Authenticate with HashiCorp Vault via AppRole.

        Credentials can be passed directly or loaded from environment:
            HCVAULT_ROLE_ID — AppRole role ID
            HCVAULT_SECRET_ID — AppRole secret ID (typically injected by orchestrator)

        For development, a root token can be set via HCVAULT_TOKEN.
        """
        self._client = hvac.Client(
            url=self._hv_config.url,
            timeout=self._hv_config.timeout,
            verify=self._hv_config.tls_verify,
        )

        # Dev mode: direct token auth
        dev_token = os.getenv("HCVAULT_TOKEN")
        if dev_token:
            self._client.token = dev_token
            if self._client.is_authenticated():
                logger.info("Authenticated with HashiCorp Vault (dev token)")
                return
            raise SecretsAuthError("Dev token authentication failed")

        # Production: AppRole auth
        _role_id = role_id or os.getenv("HCVAULT_ROLE_ID")
        _secret_id = secret_id or os.getenv("HCVAULT_SECRET_ID")

        if not _role_id or not _secret_id:
            raise SecretsAuthError(
                "AppRole credentials not provided. Set HCVAULT_ROLE_ID and "
                "HCVAULT_SECRET_ID environment variables."
            )

        for attempt in range(1, self._hv_config.retry_attempts + 1):
            try:
                result = self._client.auth.approle.login(
                    role_id=_role_id,
                    secret_id=_secret_id,
                )
                self._token = result["auth"]["client_token"]
                self._lease_id = result["auth"].get("lease_id")
                self._client.token = self._token

                logger.info(
                    "Authenticated with HashiCorp Vault via AppRole (attempt %d)",
                    attempt,
                )

                # Start token renewal thread
                lease_duration = result["auth"].get("lease_duration", 3600)
                self._start_renewal(lease_duration)
                return

            except hvac.exceptions.InvalidRequest as e:
                raise SecretsAuthError(f"AppRole auth rejected: {e}") from e
            except Exception as e:
                logger.warning(
                    "HashiCorp Vault auth attempt %d/%d failed: %s",
                    attempt, self._hv_config.retry_attempts, e,
                )
                if attempt < self._hv_config.retry_attempts:
                    time.sleep(self._hv_config.retry_delay)
                else:
                    raise SecretsAuthError(
                        f"Failed to authenticate after {self._hv_config.retry_attempts} attempts"
                    ) from e

    def _start_renewal(self, lease_duration: int) -> None:
        """Start background thread to renew token before expiry."""
        self._renewal_running = True
        renewal_interval = max(lease_duration // 2, 30)

        def _renew_loop():
            while self._renewal_running:
                time.sleep(renewal_interval)
                try:
                    self._client.auth.token.renew_self()
                    logger.debug("HashiCorp Vault token renewed")
                except Exception as e:
                    logger.error("Token renewal failed: %s", e)

        self._renewal_thread = threading.Thread(
            target=_renew_loop,
            daemon=True,
            name="hcvault-token-renewal",
        )
        self._renewal_thread.start()

    # ── Static Secrets (KV v2) ──────────────────────────────────────

    def get(self, path: str, key: Optional[str] = None) -> str:
        """
        Get a secret value from KV v2.

        Args:
            path: Secret path (e.g., "anthropic/api_key" or "wazuh/credentials")
            key: Specific key within the secret data. If None and the secret
                 has a single key, returns that value. If the path includes
                 the key (e.g., "anthropic/api_key"), it's parsed automatically.

        Returns:
            Secret value as string
        """
        # Parse path/key format
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and key is None:
            path, key = parts[0], parts[1]

        # Check cache
        cache_key = f"static:{path}"
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self._cache_ttl:
            data = cached["data"]
        else:
            data = self._read_kv(path)
            self._cache[cache_key] = {"data": data, "ts": time.time()}

        if key:
            if key not in data:
                raise SecretsError(f"Key '{key}' not found at path '{path}'")
            return data[key]

        # If no key specified and single value, return it
        if len(data) == 1:
            return next(iter(data.values()))

        raise SecretsError(
            f"Multiple keys at '{path}': {list(data.keys())}. Specify a key."
        )

    def get_all(self, path: str) -> Dict[str, str]:
        """
        Get all key-value pairs at a secret path.

        Args:
            path: Secret path (e.g., "wazuh" returns all wazuh credentials)

        Returns:
            Dict of key → value
        """
        cache_key = f"static:{path}"
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self._cache_ttl:
            return cached["data"]

        data = self._read_kv(path)
        self._cache[cache_key] = {"data": data, "ts": time.time()}
        return data

    def _read_kv(self, path: str) -> Dict[str, str]:
        """Read from KV v2 secrets engine."""
        try:
            result = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.STATIC_MOUNT,
            )
            return result["data"]["data"]
        except hvac.exceptions.InvalidPath:
            raise SecretsError(f"Secret not found: {path}")
        except hvac.exceptions.Forbidden:
            raise SecretsAuthError(
                f"Access denied to secret '{path}'. Check AppRole policy."
            )
        except Exception as e:
            raise SecretsError(f"Failed to read secret '{path}': {e}") from e

    # ── Dynamic Secrets ─────────────────────────────────────────────

    def get_dynamic(self, path: str) -> Dict[str, Any]:
        """
        Get dynamic credentials (e.g., database creds with TTL).

        Args:
            path: Dynamic secret path (e.g., "database/creds/vault-iam-role")

        Returns:
            Dict with credentials and lease info
        """
        try:
            result = self._client.read(f"{self.DYNAMIC_MOUNT}/{path}")
            return {
                "data": result["data"],
                "lease_id": result["lease_id"],
                "lease_duration": result["lease_duration"],
            }
        except hvac.exceptions.InvalidPath:
            raise SecretsError(f"Dynamic secret not found: {path}")
        except hvac.exceptions.Forbidden:
            raise SecretsAuthError(f"Access denied to dynamic secret '{path}'")
        except Exception as e:
            raise SecretsError(f"Failed to get dynamic secret '{path}': {e}") from e

    # ── Lifecycle ───────────────────────────────────────────────────

    def invalidate_cache(self, path: Optional[str] = None) -> None:
        """Invalidate cached secrets."""
        if path:
            self._cache.pop(f"static:{path}", None)
        else:
            self._cache.clear()

    def close(self) -> None:
        """Stop renewal thread and clean up."""
        self._renewal_running = False
        if self._renewal_thread:
            self._renewal_thread.join(timeout=5)
        if self._client:
            self._client.adapter.close()
        logger.info("HashiCorp Vault client closed")

    @property
    def is_authenticated(self) -> bool:
        return self._client is not None and self._client.is_authenticated()
