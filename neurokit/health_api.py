import json
import logging
import time
import pika
from threading import Thread
from typing import Optional, Callable, Dict
from fastapi import FastAPI
import psutil
from .models import HealthPayload, HealthStatus, NetworkHealth
from .utils import validate_neuro_env

logging.basicConfig(level=logging.INFO)

def get_system_load() -> int:
    """Compute weighted CPU/mem load for health reporting."""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    return min(100, int((cpu + mem) / 2))

class HealthEndpoint:
    """Manages /health endpoint payload for Consul polling."""
    def __init__(self, uid: str, custom_check: Callable[[], Dict] = lambda: {}):
        self.uid = uid
        self.custom_check = custom_check

    def payload(self, status: HealthStatus = HealthStatus.PASSING) -> Dict:
        return HealthPayload(
            uid=self.uid,
            load=get_system_load(),
            status=status,
            custom=self.custom_check()
        ).model_dump()

    def add_to_app(self, app: FastAPI, prefix: str = "/health"):
        """Mount /health to a FastAPI app."""
        @app.get(prefix)
        async def health():
            payload = self.payload()
            logging.info(f"/health polled: {payload}")
            return payload

# Convenience for quick app creation (if needed in components)
def create_health_app(uid: str, custom_check: Callable[[], Dict] = lambda: {}):
    app = FastAPI(title="NeuroKit Health")
    health = HealthEndpoint(uid=uid, custom_check=custom_check)
    health.add_to_app(app)
    return app

class HealthMonitor(Thread):
    """Subscribes to health_check_queue for neuro-network broadcasts."""
    def __init__(self, callback: Optional[Callable[[Dict], None]] = None):
        super().__init__(daemon=True)
        self.state: Dict = {"neuro_network_status": "initializing"}
        self.callback = callback
        self.running = True

    def run(self):
        config = validate_neuro_env()
        params = pika.ConnectionParameters(
            host=config["CONDUCTOR_HOST"],
            port=5672,
            credentials=pika.PlainCredentials(
                os.getenv("RABBITMQ_USER"), os.getenv("RABBITMQ_PASS")
            )
        )
        while self.running:
            try:
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                channel.queue_declare("health_check_queue", durable=True)
                channel.basic_qos(prefetch_count=1)

                def on_message(ch, method, properties, body):
                    try:
                        self.state = json.loads(body)
                        if self.callback:
                            self.callback(self.state)
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                    except json.JSONDecodeError as e:
                        logging.error(f"Invalid health broadcast JSON: {e}")
                        ch.basic_nack(delivery_tag=method.delivery_tag)

                channel.basic_consume(queue="health_check_queue", on_message_callback=on_message)
                channel.start_consuming()
            except Exception as e:
                logging.error(f"Health monitor connection error: {e}")
                time.sleep(5)  # Retry backoff

    def stop(self):
        self.running = False
