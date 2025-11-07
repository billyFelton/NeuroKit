import os
import socket
import ipaddress
from typing import Dict

class NeuroKitEnvError(EnvironmentError):
    """Custom exception for neuro-network env issues."""
    pass

def validate_neuro_env() -> Dict[str, str]:
    """
    Validate and return required/shared env vars for neuro-network integration.
    Raise NeuroKitEnvError on issues. Call early in entrypoints.
    """
    required = {
        "CONDUCTOR_HOST": {
            "value": os.getenv("CONDUCTOR_HOST"),
            "validator": _validate_conductor_host
        },
        "RABBITMQ_USER": {
            "value": os.getenv("RABBITMQ_USER"),
            "validator": _validate_non_empty
        },
        "RABBITMQ_PASS": {
            "value": os.getenv("RABBITMQ_PASS"),
            "validator": _validate_non_empty
        },
    }

    missing_or_invalid = []
    config = {}

    for var, info in required.items():
        if not info["value"]:
            missing_or_invalid.append(f"{var} missing")
            continue
        try:
            validated = info["validator"](info["value"])
            config[var] = validated
        except ValueError as e:
            missing_or_invalid.append(f"{var} invalid: {str(e)}")

    if missing_or_invalid:
        raise NeuroKitEnvError(
            "Neuro-network integration failed: " + "; ".join(missing_or_invalid) +
            ". Set in container env (docker-compose.yml or .env). Example: CONDUCTOR_HOST=10.1.1.20"
        )

    # Optionals with defaults
    config["HEALTH_PORT"] = int(os.getenv("HEALTH_PORT", "8081"))
    if not (1024 <= config["HEALTH_PORT"] <= 65535):
        raise NeuroKitEnvError(f"HEALTH_PORT {config['HEALTH_PORT']} out of range")

    config["NEUROKIT_DATA_DIR"] = os.getenv("NEUROKIT_DATA_DIR", "/data/neurokit")
    os.makedirs(config["NEUROKIT_DATA_DIR"], exist_ok=True)

    config["HOST_IP"] = os.getenv("HOST_IP") or _auto_detect_ip()
    _validate_subnet(config["HOST_IP"])  # Reuse for self

    return config

def _validate_non_empty(val: str) -> str:
    if not val.strip():
        raise ValueError("empty or whitespace")
    return val.strip()

def _validate_conductor_host(val: str) -> str:
    val = _validate_non_empty(val)
    _validate_ipv4(val)
    _validate_subnet(val)
    return val

def _validate_ipv4(val: str):
    try:
        ipaddress.ip_address(val)
    except ValueError:
        raise ValueError("not a valid IPv4")

def _validate_subnet(val: str):
    net = ipaddress.ip_network("10.1.1.0/24")
    if ipaddress.ip_address(val) not in net:
        raise ValueError("not in LAN subnet 10.1.1.0/24")

def _auto_detect_ip() -> str:
    try:
        # Connect to Conductor (if reachable) for local IP; fallback to hostname
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((os.getenv("CONDUCTOR_HOST", "10.1.1.20"), 5672))
        return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())
