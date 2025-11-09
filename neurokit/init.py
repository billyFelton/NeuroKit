"""
NeuroKit: Core library for neuro-network registration, health, and comms.
"""

# Safe imports—defers to submodules
from .models import ServiceType, RegisterStatus, HealthStatus, RegisterPayload, HealthPayload, NetworkHealth
from .utils import validate_neuro_env, NeuroKitEnvError
from .client import register_with_conductor
from .health import HealthEndpoint, HealthMonitor, get_system_load, create_health_app

__version__ = "0.3.0"
__all__ = [
    "ServiceType", "RegisterStatus", "HealthStatus", "RegisterPayload", "HealthPayload", "NetworkHealth",
    "validate_neuro_env", "NeuroKitEnvError", "register_with_conductor",
    "HealthEndpoint", "HealthMonitor", "get_system_load", "create_health_app"
]
