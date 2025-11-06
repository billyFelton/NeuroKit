"""
NeuroKit: Core for NeuroNetwork—conversational AI with ML on low-spec Ubuntu Docker.
Integrates Vox (chat API), Cadre (training), Vault (data/history), Conductor (orch).
"""

__version__ = '0.1.1'
from .core import register_service, health_report
from .signals import preprocess_signals, extract_features, simulate_eeg  # Your stub merged
from .convo import init_session, update_context
from .health import check_network_health
from .utils import log_to_vault, get_node_config

__all__ = [
    'register_service', 'health_report',
    'preprocess_signals', 'extract_features', 'simulate_eeg',
    'init_session', 'update_context',
    'check_network_health', 'log_to_vault', 'get_node_config'
]
