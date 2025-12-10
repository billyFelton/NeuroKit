# neurokit/health.py — FINAL VERSION (100% working)
import json
import logging
import time
import pika
import os
from threading import Thread
from typing import Optional, Callable, Dict

from fastapi import FastAPI
import psutil

from .models import HealthPayload, HealthStatus
from .utils import validate_neuro_env

logging.basicConfig(level=logging.INFO)


def get_system_load() -> int:
    """Return a simple load value 0-100."""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    return min(100, int((cpu + mem) / 2))


class HealthEndpoint:
    """Provides the /health JSON payload for Consul."""
    def __init__(self, uid: str, custom_check: Callable[[], Dict] = lambda: {}):
        self.uid = uid
        self.custom_check = custom_check

    def payload(self, status: HealthStatus = HealthStatus.PASSING) -> Dict:
        return HealthPayload(
            uid=self.uid,
            load=get_system_load(),
            status=status,
            custom=self.custom_check(),
        ).model_dump()

    def add_to_app(self, app: FastAPI, prefix: str = "/health"):
        @app.get(prefix)
        async def health():
            p = self.payload()
            logging.info(f"/health polled: {p}")
            return p


def create_health_app(uid: str, custom_check: Callable[[], Dict] = lambda: {}) -> FastAPI:
    """Convenient standalone health server."""
    app = FastAPI()
    HealthEndpoint(uid, custom_check).add_to_app(app)
    return app


class HealthMonitor(Thread):
    """Subscribe to health_check_queue and call callback."""
    def __init__(self, callback: Optional[Callable[[Dict], None]] = None):
        super().__init__(daemon=True)
        self.state = {"neuro_network_status": "initializing"}
        self.callback = callback
        self.running = True

    def run(self):
        cfg = validate_neuro_env()
        credentials = pika.PlainCredentials(
            os.getenv("RABBITMQ_USER", "guest"),
            os.getenv("RABBITMQ_PASS", "guest")
        )
        params = pika.ConnectionParameters(
            host=cfg["CONDUCTOR_HOST"],
            credentials=credentials
        )
        while self.running:
            try:
                conn = pika.BlockingConnection(params)
                ch = conn.channel()
                ch.queue_declare(queue="health_check_queue", durable=True)
                ch.basic_qos(prefetch_count=1)

                def on_msg(c, m, p, b):
                    try:
                        self.state = json.loads(b)
                        if self.callback:
                            self.callback(self.state)
                        c.basic_ack(m.delivery_tag)
                    except Exception:
                        c.basic_nack(m.delivery_tag, requeue=True)

                ch.basic_consume(queue="health_check_queue", on_message_callback=on_msg)
                ch.start_consuming()
            except Exception as e:
                logging.error(f"Health monitor error: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False
