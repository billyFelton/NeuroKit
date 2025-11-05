import socket
import uuid
import time
import json
from pathlib import Path

def get_host_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

def generate_uid():
    return str(uuid.uuid4())[:8]

def now():
    return time.time()

def load_state(service):
    path = Path(f"/persist/{service}/state.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"uid": None, "status": "New"}

def save_state(service, state):
    path = Path(f"/persist/{service}/state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
