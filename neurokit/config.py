"""
Centralized configuration for NeuroKit services.

All configuration is loaded from environment variables with sensible defaults.
Each container sets its own env vars at deploy time.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RabbitMQConfig:
    host: str = "rabbitmq"
    port: int = 5672
    username: str = "neuro"
    password: str = ""
    vhost: str = "/neuro"
    heartbeat: int = 60
    connection_attempts: int = 5
    retry_delay: float = 3.0
    prefetch_count: int = 10

    # Exchange names
    operational_exchange: str = "neuro.operational"
    audit_exchange: str = "neuro.audit"
    dead_letter_exchange: str = "neuro.dlx"


@dataclass
class HashiCorpVaultConfig:
    """Configuration for HashiCorp Vault (secrets only)."""
    url: str = "http://hcvault:8200"
    timeout: int = 10
    retry_attempts: int = 3
    retry_delay: float = 1.0
    tls_verify: bool = True
    # AppRole credentials come from env vars:
    #   HCVAULT_ROLE_ID, HCVAULT_SECRET_ID
    # Dev token: HCVAULT_TOKEN


@dataclass
class VaultIAMConfig:
    """Configuration for the Vault-IAM service (identity, RBAC)."""
    url: str = "http://vault-iam:8080"
    timeout: int = 10
    retry_attempts: int = 3
    retry_delay: float = 1.0


@dataclass
class VaultAuditConfig:
    """Configuration for the Vault-Audit service (audit log queries)."""
    url: str = "http://vault-audit:8081"
    timeout: int = 10


@dataclass
class PostgresConfig:
    """Configuration for Postgres (used by Vault-IAM and Vault-Audit containers)."""
    host: str = "vault-db"
    port: int = 5432
    database: str = "neuro_vault"
    username: str = "neuro"
    password: str = ""
    # Connection pool
    min_connections: int = 2
    max_connections: int = 10
    # Schemas
    iam_schema: str = "iam"
    audit_schema: str = "audit"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass
class ConductorConfig:
    url: str = "http://conductor:8080"
    heartbeat_interval: int = 30
    timeout: int = 10


@dataclass
class AuditConfig:
    enabled: bool = True
    include_prompt_text: bool = False  # If False, store hash only (safer for SOC2)
    include_response_text: bool = False
    hash_algorithm: str = "sha256"
    retention_days: int = 365  # SOC2 minimum 1 year


@dataclass
class NeuroConfig:
    """
    Master configuration object for any NeuroKit-powered container.

    Usage:
        config = NeuroConfig.from_env()
        # or with overrides:
        config = NeuroConfig.from_env(service_name="connector-wazuh")
    """

    service_name: str = "unknown"
    service_version: str = "0.0.0"
    environment: str = "development"  # development, staging, production
    log_level: str = "INFO"

    rabbitmq: RabbitMQConfig = field(default_factory=RabbitMQConfig)
    hashicorp_vault: HashiCorpVaultConfig = field(default_factory=HashiCorpVaultConfig)
    vault_iam: VaultIAMConfig = field(default_factory=VaultIAMConfig)
    vault_audit: VaultAuditConfig = field(default_factory=VaultAuditConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    conductor: ConductorConfig = field(default_factory=ConductorConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)

    @classmethod
    def from_env(cls, service_name: Optional[str] = None) -> "NeuroConfig":
        """Load configuration from environment variables."""
        return cls(
            service_name=service_name or os.getenv("NEURO_SERVICE_NAME", "unknown"),
            service_version=os.getenv("NEURO_SERVICE_VERSION", "0.0.0"),
            environment=os.getenv("NEURO_ENVIRONMENT", "development"),
            log_level=os.getenv("NEURO_LOG_LEVEL", "INFO"),
            rabbitmq=RabbitMQConfig(
                host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
                port=int(os.getenv("RABBITMQ_PORT", "5672")),
                username=os.getenv("RABBITMQ_USERNAME", "neuro"),
                password=os.getenv("RABBITMQ_PASSWORD", ""),
                vhost=os.getenv("RABBITMQ_VHOST", "/neuro"),
                heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT", "60")),
                connection_attempts=int(os.getenv("RABBITMQ_CONN_ATTEMPTS", "5")),
                retry_delay=float(os.getenv("RABBITMQ_RETRY_DELAY", "3.0")),
                prefetch_count=int(os.getenv("RABBITMQ_PREFETCH", "10")),
            ),
            hashicorp_vault=HashiCorpVaultConfig(
                url=os.getenv("HCVAULT_URL", "http://hcvault:8200"),
                timeout=int(os.getenv("HCVAULT_TIMEOUT", "10")),
                retry_attempts=int(os.getenv("HCVAULT_RETRY_ATTEMPTS", "3")),
                retry_delay=float(os.getenv("HCVAULT_RETRY_DELAY", "1.0")),
                tls_verify=os.getenv("HCVAULT_TLS_VERIFY", "true").lower() == "true",
            ),
            vault_iam=VaultIAMConfig(
                url=os.getenv("VAULT_IAM_URL", "http://vault-iam:8080"),
                timeout=int(os.getenv("VAULT_IAM_TIMEOUT", "10")),
                retry_attempts=int(os.getenv("VAULT_IAM_RETRY_ATTEMPTS", "3")),
                retry_delay=float(os.getenv("VAULT_IAM_RETRY_DELAY", "1.0")),
            ),
            vault_audit=VaultAuditConfig(
                url=os.getenv("VAULT_AUDIT_URL", "http://vault-audit:8081"),
                timeout=int(os.getenv("VAULT_AUDIT_TIMEOUT", "10")),
            ),
            postgres=PostgresConfig(
                host=os.getenv("POSTGRES_HOST", "vault-db"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "neuro_vault"),
                username=os.getenv("POSTGRES_USER", "neuro"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
                min_connections=int(os.getenv("POSTGRES_MIN_CONN", "2")),
                max_connections=int(os.getenv("POSTGRES_MAX_CONN", "10")),
            ),
            conductor=ConductorConfig(
                url=os.getenv("CONDUCTOR_URL", "http://conductor:8080"),
                heartbeat_interval=int(os.getenv("CONDUCTOR_HEARTBEAT", "30")),
                timeout=int(os.getenv("CONDUCTOR_TIMEOUT", "10")),
            ),
            audit=AuditConfig(
                enabled=os.getenv("AUDIT_ENABLED", "true").lower() == "true",
                include_prompt_text=os.getenv("AUDIT_INCLUDE_PROMPTS", "false").lower() == "true",
                include_response_text=os.getenv("AUDIT_INCLUDE_RESPONSES", "false").lower() == "true",
                hash_algorithm=os.getenv("AUDIT_HASH_ALGO", "sha256"),
                retention_days=int(os.getenv("AUDIT_RETENTION_DAYS", "365")),
            ),
        )
