import logging
import os
import uvicorn
from fastapi import FastAPI
from neurokit.utils import validate_neuro_env, NeuroKitEnvError
from neurokit.client import register_with_conductor
from neurokit.health import HealthEndpoint, HealthMonitor, HealthStatus
from neurokit.models import ServiceType

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

try:
    config = validate_neuro_env()
    logging.info(f"Neuro-network env validated: Conductor={config['CONDUCTOR_HOST']}, Host IP={config['HOST_IP']}")
except NeuroKitEnvError as e:
    logging.critical(f"Env validation failed: {e}")
    exit(1)

role = os.getenv("NEURO_ROLE")
if role not in ["vox", "vault", "cadre", "cadre_light"]:
    logging.critical("NEURO_ROLE must be vox/vault/cadre/cadre_light")
    exit(1)

service_map = {
    "vox": "vox",
    "vault": "vault",
    "cadre": "cadre",
    "cadre_light": "cadre_light"
}
service = service_map[role]

api_port = int(os.getenv("API_PORT", "8000"))  # Dummy; not used but for realism

# Registration
try:
    uid = register_with_conductor(service=service, port=api_port, host=config["HOST_IP"])
    logging.info(f"Registered as {service} with UID: {uid}")
except Exception as e:
    logging.critical(f"Registration failed: {e}")
    exit(1)

# Dummy custom health (component-specific would extend this)
def custom_check():
    return {"simulated": True, "role": role}

health = HealthEndpoint(uid=uid, custom_check=custom_check)

# /health API (Consul polls this)
app = FastAPI()
@app.get("/health")
async def health_endpoint():
    status = HealthStatus.PASSING  # Or dynamic based on fake load
    payload = health.payload(status=status)
    logging.info(f"/health polled: {payload}")
    return payload

# HealthMonitor subscriber (logs broadcasts)
def on_health_update(state: dict):
    logging.info(f"Neuro-network health update: {state}")

HealthMonitor(callback=on_health_update).start()
logging.info("Subscribed to health_check_queue - logging all Conductor broadcasts")

# Keep alive with uvicorn for /health
logging.info(f"Starting dummy /health server on port {config['HEALTH_PORT']}")
uvicorn.run(app, host="0.0.0.0", port=config["HEALTH_PORT"])
