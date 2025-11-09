from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, List
import ipaddress

class ServiceType(str, Enum):
    VOX = "vox"
    CONDUCTOR = "conductor"
    VAULT = "vault"
    CADRE = "cadre"
    CADRE_LIGHT = "cadre_light"

class RegisterStatus(str, Enum):
    NEW = "New"
    REBOOTING = "Rebooting"
    FAULT = "Fault"

class HealthStatus(str, Enum):
    PASSING = "passing"
    WARNING = "warning"
    CRITICAL = "critical"
    FAULT = "fault"

class RegisterPayload(BaseModel):
    service: ServiceType
    uid: Optional[str] = None  # None for "New"
    host: str = Field(..., description="IPv4 in 10.1.1.0/24")
    port: int
    load: int = Field(0, ge=0, le=100)
    status: RegisterStatus

    @validator('host')
    def validate_subnet(cls, v):
        ip = ipaddress.ip_address(v)
        net = ipaddress.ip_network('10.1.1.0/24')
        if ip not in net:
            raise ValueError("Host not in LAN subnet")
        return v

class HealthPayload(BaseModel):
    uid: str
    load: int
    status: HealthStatus
    custom: Dict = {}

class NetworkHealth(BaseModel):
    neuro_network_status: str
    fullness_pct: float
    core_services_ready: bool
    services: List[Dict]
