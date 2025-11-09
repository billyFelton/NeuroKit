import psutil
import json
import pika
import logging
import time  # For retry sleeps
from threading import Thread
from typing import Optional, Callable, Dict
from fastapi import FastAPI
from .models import HealthPayload, HealthStatus, NetworkHealth
from .utils import validate_neuro_env

def get_system_load() -> int:
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    return min(100, int((cpu + mem) / 2))

class HealthEndpoint:
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
        @app.get(f"{prefix}")
        async def health():
            return self.payload()

# Optional: Convenience function if you had create_health_app
def create_health_app(uid: str, custom_check: Callable[[], Dict] = lambda: {}):
    app = FastAPI()
    health = HealthEndpoint(uid=uid, custom_check=custom_check)
    health.add_to_app(app)
    return app

class HealthMonitor(Thread):
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
                    self.state = json.loads(body)
                    if self.callback:
                        self.callback(self.state)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(queue="health_check_queue", on_message_callback=on_message)
                channel.start_consuming()
            except Exception as e:
                logging.error(f"Health monitor error: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False
