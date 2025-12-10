# NeuroKit

Shared API for NeuroNetwork components.

## Install

```bash
pip install NeuroKit

# NeuroKit: NeuroNetwork Core Library

Lightweight Python lib for your AI setup: Signal processing, convo state, orchestration, and health monitoring. Runs in Docker on 4-core/2.4GHz/8GB Ubuntu 24.04 nodes (64GB storage).

## Install in Containers
In Cadre/Vox/Conductor Dockerfile:


## Usage Examples
- **Vox Startup (10.1.1.10)**: `from neurokit.core import register_service; register_service('vox-01', 'http://10.1.1.10:5000', 'node-10.1.1.10')`
- **Cadre Training (10.1.1.40)**: `from neurokit.signals import preprocess_signals, extract_features; feats = extract_features(preprocess_signals(raw_data))`  # Feed to TF/PyTorch
- **Conductor Health**: `from neurokit.health import check_network_health; if check_network_health()['status'] == 'healthy': print('Neuro-network limited but ready')`
- **Vault Logging**: `from neurokit.utils import log_to_vault; log_to_vault('convo_history', {'session': session_id, 'data': context})`

## Env Vars (Docker Compose)
- `CONDUCTOR_RMQ_URL=amqp://guest:guest@10.1.1.20:5672`
- `VAULT_DB_URL=postgresql://postgres:pass@10.1.1.30:5432/neurovault`
- `PROMETHEUS_URL=http://10.1.1.20:9091`

## Modules
- **core**: Service rego/health report to Conductor (RabbitMQ/Consul).
- **signals**: Neuro-signal prep/feats for Cadre (NFS load from Vault).
- **convo**: Session init/update for Vox API, persist to Vault Postgres.
- **health**: Network status check (all components online = healthy limited).
- **utils**: Config/log helpers (storage fullness alerts at 80% of 64GB).

Extensible: Add cloud (e.g., S3 hooks) later. MIT license.
