from .registration import register
from .health import start_health_server

def init_component(service, port):
    state = register(service, port)
    start_health_server(port, service)
    return state["uid"]
