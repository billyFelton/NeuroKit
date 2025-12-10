# neurokit/utils.py
import os
import socket
import ipaddress
import logging
from typing import Dict


class NeuroKitEnvError(EnvironmentError):
    """Custom exception for neuro-network env issues."""
    pass


def validate_neuro_env() -> Dict[str, str]:
    """
    Validate required env vars for neuro-network integration.
    Raise NeuroKitEnvError on issues.
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
            ". Set in container env (docker-compose.yml or .env)."
        )

    # Optional settings with safe defaults
    config["HEALTH_PORT"] = int(os.getenv("HEALTH_PORT", "8081"))
    if not (1024 <= config["HEALTH_PORT"] <= 65535):
        raise NeuroKitEnvError(f"HEALTH_PORT {config['HEALTH_PORT']} out of range")

    config["NEUROKIT_DATA_DIR"] = os.getenv("NEUROKIT_DATA_DIR", "/data/neurokit")
    os.makedirs(config["NEUROKIT_DATA_DIR"], exist_ok=True)

    # HOST_IP: prefer explicit env var, otherwise auto-detect (perfect in network_mode: host)
    host_ip = os.getenv("HOST_IP")
    if host_ip:
        config["HOST_IP"] = host_ip
        logging.info(f"Using explicit HOST_IP from environment: {host_ip}")
    else:
        config["HOST_IP"] = _auto_detect_ip()
        logging.info(f"Auto-detected HOST_IP: {config['HOST_IP']} (host network mode)")

    return config


def _validate_non_empty(val: str) -> str:
    if not val.strip():
        raise ValueError("empty or whitespace")
    return val.strip()


def _validate_conductor_host(val: str) -> str:
    val = _validate_non_empty(val)
    try:
        ipaddress.ip_address(val)
    except ValueError:
        raise ValueError("not a valid IPv4 address")
    return val


def _auto_detect_ip() -> str:
    """Return the IP used to reach Conductor — correct in host network mode."""
    try:
        conductor_host = os.getenv("CONDUCTOR_HOST", "10.1.1.20")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((conductor_host, 5672))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logging.warning(f"Auto-detect failed ({e}), falling back to gethostname")
        return socket.gethostbyname(socket.gethostname())
