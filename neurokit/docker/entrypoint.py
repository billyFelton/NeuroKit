import os
import logging
import time
import uvicorn
from fastapi import FastAPI
from neurokit.utils import validate_neuro_env, NeuroKitEnvError
from neurokit.client import register_with_conductor
from neurokit.health import HealthEndpoint, HealthMonitor, HealthStatus
from neurokit.models import ServiceType

logging.basicConfig(level=logging.INFO, format='[SIM %(levelname)s] %(message)s')

try:
    config = validate_neuro_env()
    logging.info(f"Neuro env validated - Conductor: {config['CONDUCTOR_HOST']}")
except NeuroKitEnvError as e:
    logging.critical(f"Env validation failed: {e}")
    exit(1)

role = os.getenv("NEURO_ROLE", "vox")
if role not in ["vox", "vault", "cadre", "cadre_light"]:
    logging.critical("NEURO_ROLE must be one of: vox, vault, cadre, cadre_light")
    exit(1)

service = role  # Maps directly to enum value

api_port = int(os.getenv("API_PORT", "8000"))

# Registration
try:
    uid = register_with_conductor(service=service, port=api_port)
    logging.info(f"SIMULATED {role.upper()} REGISTERED - UID: {uid}")
except Exception as e:
    logging.critical(f"Registration failed: {e}")
    exit(1)

# Custom check for sim
def custom_check():
    return {"simulated": True, "role": role}

health = HealthEndpoint(uid=uid, custom_check=custom_check)

# FastAPI app for /health
app = FastAPI()
health.add_to_app(app)

# Health monitor
def on_health_update(state: dict):
    logging.info(f"HEALTH BROADCAST: {state['neuro_network_status']} | Fullness: {state.get('fullness_pct', 0)}% | Ready: {state.get('core_services_ready', False)}")

monitor = HealthMonitor(callback=on_health_update)
monitor.start()
logging.info("Subscribed to health_check_queue")

# Run server
logging.info(f"Starting /health on port {config['HEALTH_PORT']}")
uvicorn.run(app, host="0.0.0.0", port=config["HEALTH_PORT"])
