from flask import Flask, jsonify
import threading
import time
import pika
import json
import psutil
from .utils import get_host_ip, now, load_state, save_state

app = Flask(__name__)

def calculate_load():
    return int((psutil.cpu_percent() + psutil.virtual_memory().percent) / 2)

@app.route("/health")
def health():
    state = load_state("vox")  # Dynamic per service
    return jsonify({
        "uid": state["uid"],
        "status": "passing",
        "load": calculate_load(),
        "uptime": now() - state.get("start_time", now()),
        "host": get_host_ip()
    })

def start_health_server(port, service):
    def _run():
        app.run(host="0.0.0.0", port=port, use_reloader=False)

    threading.Thread(target=_run, daemon=True).start()

    state = load_state(service)
    state["start_time"] = now()
    save_state(service, state)

    def heartbeat():
        credentials = pika.PlainCredentials("conductor_user", "conductor_pass")
        parameters = pika.ConnectionParameters(host="rabbitmq", credentials=credentials)
        while True:
            try:
                conn = pika.BlockingConnection(parameters)
                ch = conn.channel()
                ch.queue_declare(queue="health_check_queue", durable=True)
                payload = {
                    "uid": state["uid"],
                    "load": calculate_load(),
                    "status": "passing",
                    "timestamp": now(),
                }
                ch.basic_publish(
                    exchange="",
                    routing_key="health_check_queue",
                    body=json.dumps(payload).encode(),
                )
                conn.close()
            except Exception as e:
                print(f"Heartbeat failed: {e}")
            time.sleep(15)

    threading.Thread(target=heartbeat, daemon=True).start()
