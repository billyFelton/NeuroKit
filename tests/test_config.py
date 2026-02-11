"""Tests for NeuroConfig environment variable loading."""

import os
import pytest
from neurokit.config import NeuroConfig


class TestNeuroConfig:
    """Test configuration loading from environment."""

    def test_defaults(self):
        config = NeuroConfig.from_env(service_name="test-service")
        assert config.service_name == "test-service"
        assert config.environment == "development"
        assert config.rabbitmq.host == "rabbitmq"
        assert config.rabbitmq.port == 5672
        assert config.hashicorp_vault.url == "http://hcvault:8200"
        assert config.vault_iam.url == "http://vault-iam:8080"
        assert config.audit.retention_days == 365
        assert config.audit.include_prompt_text is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEURO_SERVICE_NAME", "my-connector")
        monkeypatch.setenv("NEURO_ENVIRONMENT", "production")
        monkeypatch.setenv("RABBITMQ_HOST", "rmq.internal")
        monkeypatch.setenv("RABBITMQ_PORT", "5673")
        monkeypatch.setenv("HCVAULT_URL", "https://vault.internal:8200")
        monkeypatch.setenv("AUDIT_INCLUDE_PROMPTS", "true")
        monkeypatch.setenv("AUDIT_RETENTION_DAYS", "730")

        config = NeuroConfig.from_env()
        assert config.service_name == "my-connector"
        assert config.environment == "production"
        assert config.rabbitmq.host == "rmq.internal"
        assert config.rabbitmq.port == 5673
        assert config.hashicorp_vault.url == "https://vault.internal:8200"
        assert config.audit.include_prompt_text is True
        assert config.audit.retention_days == 730

    def test_postgres_dsn(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "db.internal")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "mydb")
        monkeypatch.setenv("POSTGRES_USER", "myuser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

        config = NeuroConfig.from_env()
        assert config.postgres.dsn == "postgresql://myuser:secret@db.internal:5433/mydb"
