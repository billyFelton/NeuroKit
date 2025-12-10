# neurokit/bootstrap.py
import os
import logging
from fastapi import FastAPI
import uvicorn

from .register import register_service
from .health import HealthEndpoint

logger = logging.getLogger(__name__)

def bootstrap_service(
    *,
    service_name: str,
    app: FastAPI | None = None,
    custom_health_check: dict | None = None,
    health_port_env: str = "HEALTH_PORT",
    default_health_port: int = 8081,
) -> str:
    """
    THE ONLY FUNCTION ANY SERVICE EVER CALLS.

    Does everything:
    - Validates env
    - Registers with Conductor
    - Starts minimal health server on HEALTH_PORT (for Consul only)
    - Returns UID
    - If app is provided, mounts it too (optional future use)
    """
    from .utils import validate_neuro_env
    config = validate_neuro_env()

    health_port = int(os.getenv(health_port_env, str(default_health_port)))

    uid = register_service(
        service_name=service_name,
        port=health_port,
        custom_data=custom_health_check or {}
    )

    logger.info(f"{service_name.upper()} bootstrapped — UID: {uid}")
    logger.info(f"Consul health endpoint → http://0.0.0.0:{health_port}/health")

    # Start ONLY the health server — no main API
    health_app = FastAPI()
    health_endpoint = HealthEndpoint(uid=uid, custom_check=lambda: custom_health_check or {})
    health_endpoint.add_to_app(health_app)

    if app:
        health_app.mount("/api", app)  # optional — future-proof

    uvicorn.run(health_app, host="0.0.0.0", port=health_port)
    return uid  # never reached
