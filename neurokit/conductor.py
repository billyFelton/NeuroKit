"""
Conductor client for service registration, discovery, and health reporting.

Every container registers with Conductor on startup and sends periodic
heartbeats. Conductor uses this to maintain the service registry and
route requests to healthy instances.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from neurokit.config import NeuroConfig

logger = logging.getLogger("neurokit.conductor")


class ConductorClient:
    """
    Client for the Conductor orchestration service.

    Handles service registration, heartbeats, and discovery.

    Usage:
        config = NeuroConfig.from_env()
        conductor = ConductorClient(config)

        # Register this service
        conductor.register(
            capabilities=["wazuh-query", "alert-ingest"],
            metadata={"wazuh_version": "4.7"}
        )

        # Start heartbeat thread
        conductor.start_heartbeat()

        # Discover other services
        wazuh = conductor.discover("connector-wazuh")

        # On shutdown
        conductor.deregister()
    """

    def __init__(self, config: NeuroConfig):
        self.config = config
        self.conductor_config = config.conductor
        self._base_url = self.conductor_config.url.rstrip("/")
        self._instance_id: Optional[str] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running = False

        self._session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1.0, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        kwargs.setdefault("timeout", self.conductor_config.timeout)
        try:
            response = self._session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.ConnectionError as e:
            logger.warning("Cannot reach Conductor at %s: %s", self._base_url, e)
            return {}
        except requests.RequestException as e:
            logger.error("Conductor request failed: %s", e)
            return {}

    def register(
        self,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        queues: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Register this service instance with Conductor.

        Args:
            capabilities: List of capabilities this service provides
            metadata: Additional metadata (version info, config, etc.)
            queues: RabbitMQ queues this service consumes from

        Returns:
            Instance ID assigned by Conductor, or None on failure
        """
        result = self._request("POST", "/api/v1/services/register", json={
            "service_name": self.config.service_name,
            "service_version": self.config.service_version,
            "environment": self.config.environment,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "queues": queues or [],
        })

        self._instance_id = result.get("instance_id")
        if self._instance_id:
            logger.info(
                "Registered with Conductor as %s (instance=%s)",
                self.config.service_name,
                self._instance_id,
            )
        return self._instance_id

    def deregister(self) -> None:
        """Deregister this service instance from Conductor."""
        self.stop_heartbeat()
        if self._instance_id:
            self._request("DELETE", f"/api/v1/services/{self._instance_id}")
            logger.info("Deregistered from Conductor (instance=%s)", self._instance_id)
            self._instance_id = None

    def heartbeat(self, status: str = "healthy", details: Optional[Dict] = None) -> None:
        """Send a heartbeat to Conductor."""
        if not self._instance_id:
            return
        self._request("POST", f"/api/v1/services/{self._instance_id}/heartbeat", json={
            "status": status,
            "details": details or {},
        })

    def start_heartbeat(
        self,
        status_callback: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        """
        Start a background thread that sends periodic heartbeats.

        Args:
            status_callback: Optional function that returns current status details
                           (e.g., queue depth, memory usage, active connections)
        """
        if self._heartbeat_running:
            return

        self._heartbeat_running = True

        def _heartbeat_loop():
            while self._heartbeat_running:
                try:
                    details = status_callback() if status_callback else {}
                    self.heartbeat(status="healthy", details=details)
                except Exception as e:
                    logger.warning("Heartbeat failed: %s", e)
                time.sleep(self.conductor_config.heartbeat_interval)

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            daemon=True,
            name=f"conductor-heartbeat-{self.config.service_name}",
        )
        self._heartbeat_thread.start()
        logger.info(
            "Heartbeat started (interval=%ds)",
            self.conductor_config.heartbeat_interval,
        )

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread."""
        self._heartbeat_running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def discover(self, service_name: str) -> List[Dict[str, Any]]:
        """
        Discover healthy instances of a service.

        Returns:
            List of instance records with their connection details
        """
        result = self._request("GET", f"/api/v1/services/discover/{service_name}")
        instances = result.get("instances", [])
        logger.debug("Discovered %d instances of %s", len(instances), service_name)
        return instances

    def get_service_status(self) -> Dict[str, Any]:
        """Get the full Neuro-Network service registry status."""
        return self._request("GET", "/api/v1/services/status")
