"""
NeuroKit: Core library for neuro-network registration, health, and comms.
"""

from .models import ServiceType, RegisterStatus, HealthStatus, RegisterPayload, HealthPayload, NetworkHealth
from .utils import validate_neuro_env, NeuroKitEnvError
from .client import register_with_conductor
from .health import HealthEndpoint, HealthMonitor, get_system_load
import yaml
from pathlib import Path

__version__ = "0.3.0"
__all__ = [
    "ServiceType", "RegisterStatus", "HealthStatus", "RegisterPayload", "HealthPayload", "NetworkHealth",
    "validate_neuro_env", "NeuroKitEnvError", "register_with_conductor",
    "HealthEndpoint", "HealthMonitor", "get_system_load"
]
CONTRACT = yaml.safe_load(Path(__file__).parent.parent / "contract.yaml")

QUEUES = CONTRACT["queues"]
REG_SCHEMA = CONTRACT["registration_schema"]
HEALTH_SCHEMA = CONTRACT["health_schema"]
