# NeuroKit

Shared Python library for the **Neuro-Network** — a containerized AI integration platform with SOC2-compliant audit trails, RBAC enforcement, and multi-model AI orchestration.

## Installation

```bash
# From GitHub (specific version)
pip install git+https://github.com/yourorg/neurokit.git@v0.2.0

# From GitHub (latest main)
pip install git+https://github.com/yourorg/neurokit.git

# With optional dependencies
pip install "neurokit[db] @ git+https://github.com/yourorg/neurokit.git@v0.2.0"
pip install "neurokit[slack] @ git+https://github.com/yourorg/neurokit.git@v0.2.0"

# For development
git clone https://github.com/yourorg/neurokit.git
cd neurokit
pip install -e ".[all]"
```

### In a Dockerfile

```dockerfile
# Pin to a specific version tag
RUN pip install --no-cache-dir "git+https://github.com/yourorg/neurokit.git@v0.2.0"

# Or with extras
RUN pip install --no-cache-dir "neurokit[db] @ git+https://github.com/yourorg/neurokit.git@v0.2.0"
```

### In requirements.txt

```
neurokit @ git+https://github.com/yourorg/neurokit.git@v0.2.0
```

## Architecture

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐
│  Connector   │   │  Connector   │   │  Connector   │
│    Slack     │   │   Wazuh      │   │   EntraID    │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
                   ┌──────┴───────┐
                   │   RabbitMQ   │
                   └──────┬───────┘
                          │
       ┌──────────────────┼───────────────────┐
       │                  │                   │
┌──────┴───────┐   ┌──────┴───────┐   ┌──────┴───────┐
│   Resolver   │   │ Agent Router │   │  Conductor   │
└──────┬───────┘   └──────┴───────┘   └──────────────┘
       │                  │
       │           ┌──────┴───────┐
       │           │ Agent Worker │
       │           │   (Claude)   │
       │           └──────────────┘
       │
┌──────┴────────────────────────┐
│         Vault Service         │
│  ┌─────────┐  ┌────────────┐ │
│  │ HCVault  │  │  Postgres  │ │
│  └─────────┘  └────────────┘ │
│  ┌─────────┐  ┌────────────┐ │
│  │Vault-IAM│  │Vault-Audit │ │
│  └─────────┘  └────────────┘ │
└───────────────────────────────┘
```

## Quick Start

Every container subclasses `BaseService`:

```python
from neurokit.service import BaseService
from neurokit.envelope import MessageEnvelope, EventType

class MyConnector(BaseService):

    def on_startup(self):
        # Secrets from HashiCorp Vault
        self.api_key = self.secrets.get("my-service/api_key")

    def setup_queues(self):
        self.inbox = self.rmq.declare_queue(
            "my-connector.inbox",
            routing_keys=["my-service.query"]
        )
        self.rmq.consume(self.inbox, self.handle_message)

    def handle_message(self, envelope: MessageEnvelope):
        result = do_work(envelope.payload)

        self.audit.log_from_envelope(
            envelope=envelope,
            event_type=EventType.DATA_ACCESS,
            action="query",
            resource="my-resource",
        )

        return envelope.create_reply(
            source=self.service_name,
            message_type="my-service.response",
            payload={"data": result}
        )

    def get_capabilities(self):
        return ["my-service-query"]

if __name__ == "__main__":
    service = MyConnector.create("my-connector")
    service.run()
```

## Modules

| Module | Class | Purpose |
|---|---|---|
| `neurokit.config` | `NeuroConfig` | Centralized env-based configuration |
| `neurokit.envelope` | `MessageEnvelope`, `AuditEvent` | Standard message format with actor/auth/AI context |
| `neurokit.rabbitmq` | `RabbitMQClient` | Connection management, publish/consume |
| `neurokit.secrets` | `SecretsClient` | HashiCorp Vault AppRole auth and KV v2 reads |
| `neurokit.vault` | `VaultIAMClient` | Identity resolution, RBAC queries |
| `neurokit.rbac` | `RBACEnforcer` | Permission checks with audit logging |
| `neurokit.audit` | `AuditLogger` | SOC2 audit events with hash-chain tamper detection |
| `neurokit.conductor` | `ConductorClient` | Service registration, discovery, heartbeats |
| `neurokit.service` | `BaseService` | Lifecycle base class for all containers |

## Configuration

All configuration via environment variables. See `neurokit/config.py` for full reference.

## Versioning

This project uses semantic versioning. Pin to a specific version in production:

```
neurokit @ git+https://github.com/yourorg/neurokit.git@v0.2.0
```

## Related Repositories

| Repository | Description |
|---|---|
| `yourorg/neurokit` | This library (shared SDK) |
| `yourorg/vault-service` | Vault multi-container service (HCVault + IAM + Audit + Postgres) |
| `yourorg/connector-slack` | Slack connector (user-token agent) |
| `yourorg/connector-wazuh` | Wazuh SIEM connector |
| `yourorg/connector-entraid` | Microsoft EntraID connector |
| `yourorg/connector-email` | Email connector (Graph API / IMAP) |
| `yourorg/agent-worker-claude` | Claude AI worker |
| `yourorg/agent-router` | AI model routing service |
| `yourorg/resolver` | Auth enrichment and RBAC enforcement |
| `yourorg/conductor` | Service orchestration and discovery |
| `yourorg/neuro-deploy` | Docker Compose / K8s deployment configs |
