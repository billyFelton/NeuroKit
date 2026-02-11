"""
Base service class for Neuro-Network containers.

Provides a standardized lifecycle (init → connect → run → shutdown) that
handles RabbitMQ connection, Vault authentication, Conductor registration,
and audit logging setup automatically.

Every container inherits from BaseService and implements its own
setup_queues() and handle_message() methods.
"""

import logging
import signal
import sys
from typing import Any, Callable, Dict, List, Optional

from neurokit.audit import AuditLogger
from neurokit.conductor import ConductorClient
from neurokit.config import NeuroConfig
from neurokit.envelope import EventType, MessageEnvelope
from neurokit.rabbitmq import RabbitMQClient
from neurokit.rbac import RBACEnforcer
from neurokit.secrets import SecretsClient
from neurokit.vault import VaultIAMClient

logger = logging.getLogger("neurokit.service")


class BaseService:
    """
    Base class for all Neuro-Network containerized services.

    Subclass this and implement:
        - setup_queues(): Declare your RabbitMQ queues and bindings
        - handle_message(envelope): Process incoming messages
        - Optionally: on_startup(), on_shutdown(), health_status()

    Example:
        class WazuhConnector(BaseService):
            def setup_queues(self):
                self.inbox = self.rmq.declare_queue(
                    "connector-wazuh.inbox",
                    routing_keys=["wazuh.query", "wazuh.command"]
                )

            def handle_message(self, envelope: MessageEnvelope):
                if envelope.message_type == "wazuh.query":
                    alerts = self.query_wazuh(envelope.payload)
                    return envelope.create_reply(
                        source=self.service_name,
                        message_type="wazuh.response",
                        payload={"alerts": alerts}
                    )

            def on_startup(self):
                self.wazuh_token = self.secrets.get("wazuh/api_token")

        if __name__ == "__main__":
            service = WazuhConnector.create("connector-wazuh")
            service.run()
    """

    def __init__(self, config: NeuroConfig):
        self.config = config
        self.service_name = config.service_name

        # Core clients — initialized in connect()
        self.rmq: Optional[RabbitMQClient] = None
        self.secrets: Optional[SecretsClient] = None    # HashiCorp Vault (secrets only)
        self.iam: Optional[VaultIAMClient] = None       # Vault-IAM (identity, RBAC)
        self.conductor: Optional[ConductorClient] = None
        self.audit: Optional[AuditLogger] = None
        self.rbac: Optional[RBACEnforcer] = None

        self._running = False
        self._setup_logging()

    @classmethod
    def create(cls, service_name: str, **kwargs) -> "BaseService":
        """Factory method to create a service with env-based config."""
        config = NeuroConfig.from_env(service_name=service_name)
        return cls(config, **kwargs)

    def _setup_logging(self) -> None:
        """Configure structured logging."""
        log_format = (
            f"%(asctime)s [{self.service_name}] %(levelname)s "
            f"%(name)s: %(message)s"
        )
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper(), logging.INFO),
            format=log_format,
            stream=sys.stdout,
        )

    def _setup_signal_handlers(self) -> None:
        """Handle graceful shutdown signals."""
        def _shutdown(signum, frame):
            logger.info("Received signal %s, shutting down...", signum)
            self.shutdown()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

    def connect(self) -> None:
        """Initialize and connect all clients."""
        logger.info("Connecting %s v%s...", self.service_name, self.config.service_version)

        # 1. Connect to RabbitMQ
        self.rmq = RabbitMQClient(self.config)
        self.rmq.connect()

        # 2. Initialize audit logger (needs RabbitMQ)
        self.audit = AuditLogger(self.config, self.rmq)

        # 3. Connect to HashiCorp Vault for secrets (AppRole auth)
        self.secrets = SecretsClient(self.config)
        self.secrets.authenticate()

        # 4. Connect to Vault-IAM for identity and RBAC
        self.iam = VaultIAMClient(self.config)
        import os
        iam_token = os.getenv("VAULT_IAM_SERVICE_TOKEN")
        self.iam.authenticate(service_token=iam_token)

        # 5. Initialize RBAC enforcer (needs Vault-IAM + audit)
        self.rbac = RBACEnforcer(self.iam, self.audit, self.service_name)

        # 6. Register with Conductor
        self.conductor = ConductorClient(self.config)

        # Log startup audit event
        self.audit.log_system(
            action="service_starting",
            resource=self.service_name,
            details={
                "version": self.config.service_version,
                "environment": self.config.environment,
            },
        )

    def run(self) -> None:
        """
        Full service lifecycle: connect → setup → consume → shutdown.

        This is the main entry point for running a service.
        """
        self._setup_signal_handlers()

        try:
            # Connect all clients
            self.connect()

            # Let subclass do its setup
            self.on_startup()

            # Declare queues and bind handlers
            self.setup_queues()

            # Register with Conductor (after queues are ready)
            self.conductor.register(
                capabilities=self.get_capabilities(),
                metadata=self.get_metadata(),
            )
            self.conductor.start_heartbeat(status_callback=self.health_status)

            self._running = True
            self.audit.log_system(
                action="service_started",
                resource=self.service_name,
            )
            logger.info("%s is running", self.service_name)

            # Block on message consumption
            self.rmq.start_consuming()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error("Fatal error in %s: %s", self.service_name, e, exc_info=True)
            if self.audit:
                self.audit.log_system(
                    action="service_error",
                    resource=self.service_name,
                    outcome_status="error",
                    details={"error": str(e)},
                )
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Graceful shutdown: deregister, close connections, log."""
        if not self._running:
            return
        self._running = False

        logger.info("Shutting down %s...", self.service_name)

        try:
            self.on_shutdown()
        except Exception as e:
            logger.error("Error in on_shutdown: %s", e)

        if self.audit:
            self.audit.log_system(
                action="service_stopping",
                resource=self.service_name,
            )

        if self.conductor:
            self.conductor.deregister()

        if self.rmq:
            self.rmq.disconnect()

        logger.info("%s shutdown complete", self.service_name)

    # ── Methods for subclasses to override ──────────────────────────

    def setup_queues(self) -> None:
        """
        Declare RabbitMQ queues and register message handlers.
        Override in subclass.
        """
        raise NotImplementedError("Subclass must implement setup_queues()")

    def handle_message(self, envelope: MessageEnvelope) -> Optional[MessageEnvelope]:
        """
        Process an incoming message. Override in subclass.

        Return a MessageEnvelope to send a reply (if envelope has reply_to).
        Return None for fire-and-forget messages.
        """
        raise NotImplementedError("Subclass must implement handle_message()")

    def on_startup(self) -> None:
        """Called after connect() but before consuming. Override for custom init."""
        pass

    def on_shutdown(self) -> None:
        """Called during shutdown before connections close. Override for cleanup."""
        pass

    def get_capabilities(self) -> List[str]:
        """Return list of capabilities for Conductor registration. Override."""
        return []

    def get_metadata(self) -> Dict[str, Any]:
        """Return metadata for Conductor registration. Override."""
        return {
            "version": self.config.service_version,
            "environment": self.config.environment,
        }

    def health_status(self) -> Dict[str, Any]:
        """Return health details for Conductor heartbeat. Override."""
        return {
            "rabbitmq_connected": self.rmq.is_connected if self.rmq else False,
            "secrets_authenticated": self.secrets.is_authenticated if self.secrets else False,
        }
