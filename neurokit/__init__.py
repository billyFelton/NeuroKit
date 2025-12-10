"""
NeuroKit: Core library for neuro-network registration, health, and comms.
"""
import logging
from pathlib import Path
import yaml

from .models import ServiceType, RegisterStatus, HealthStatus, RegisterPayload, HealthPayload, NetworkHealth
from .utils import validate_neuro_env, NeuroKitEnvError
from .client import register_with_conductor
from .health import HealthEndpoint, HealthMonitor, get_system_load
from .register import register_service   # ← THIS LINE WAS MISSING
from .bootstrap import bootstrap_service

__version__ = "0.3.0"
__all__ = [
    "ServiceType", "RegisterStatus", "HealthStatus", "RegisterPayload", "HealthPayload", "NetworkHealth",
    "validate_neuro_env", "NeuroKitEnvError", "register_with_conductor",
    "HealthEndpoint", "HealthMonitor", "get_system_load",
    "register_service","bootstrap_service"   # ← AND THIS
]

# Safe contract.yaml loading
try:
    contract_path = Path(__file__).parent / "contract.yaml"
    if contract_path.exists():
        with open(contract_path, "r", encoding="utf-8") as f:
            CONTRACT = yaml.safe_load(f) or {}
    else:
        logging.warning("contract.yaml not found")
        CONTRACT = {}
except Exception as e:
    logging.error(f"Failed to load contract.yaml: {e}")
    CONTRACT = {}

QUEUES = CONTRACT.get("queues", [])
REG_SCHEMA = CONTRACT.get("registration_schema", {})
HEALTH_SCHEMA = CONTRACT.get("health_schema", {})

logging.info(f"NeuroKit v{__version__} loaded — {len(QUEUES)} queues defined")
