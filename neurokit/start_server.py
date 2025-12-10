# neurokit/start_server.py
import os
import logging
import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)

def start_neurokit_server(
    app: FastAPI,
    service_name: str,
    *,
    custom_data: dict | None = None,
    health_port_env: str = "HEALTH_PORT",
    default_health_port: int = 8081,
    api_port_env: str | None = "API_PORT",        # Optional — for main API on different port
) -> None:
    """
    All-in-one function used by every service (vault, vox, cadre, etc):
    1. Reads HEALTH_PORT from environment (fallback to default)
    2. Registers with Conductor using that port
    3. Starts FastAPI server on:
         - HEALTH_PORT (default), or
         - API_PORT if provided (for services that want main API ≠ health port)
    """
    from .register import register_service

    health_port = int(os.getenv(health_port_env, str(default_health_port)))
    api_port = int(os.getenv(api_port_env, str(health_port))) if api_port_env else health_port

    # Register with Conductor — tells it where /health lives
    uid = register_service(
        service_name=service_name,
        port=health_port,                    # ← this is what Consul checks
        custom_data=custom_data or {}
    )

    logger.info(f"{service_name.upper()} READY — UID: {uid}")
    logger.info(f"Health endpoint  → http://0.0.0.0:{health_port}/health")
    if api_port != health_port:
        logger.info(f"Main API endpoint → http://0.0.0.0:{api_port}")

    # Start server on the correct port
    uvicorn.run(app, host="0.0.0.0", port=api_port)
