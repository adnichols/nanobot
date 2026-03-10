"""ACP cron handler for scheduled ACP-backed sessions.

This module provides ACPCronHandler for integrating ACP-backed sessions
with nanobot's scheduler (cron service).

Key responsibilities:
1. Route cron jobs to ACP backend when configured
2. Handle unattended permission resolution (policy-driven)
3. Deliver results back to originating channels
4. Preserve local nanobot session behavior when ACP is not configured
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

if TYPE_CHECKING:
    from nanobot.acp.permissions import ACPPermissionBroker
    from nanobot.acp.service import ACPService
    from nanobot.cron.types import CronJob


class ACPCronHandler:
    """Handler for cron jobs targeting ACP-backed sessions.

    This class provides the bridge between nanobot's cron service and
    ACP-backed sessions. It:
    - Loads/creates ACP sessions for cron job payloads
    - Uses unattended permission policy (no user interaction)
    - Delivers results back to originating channels
    """

    def __init__(
        self,
        acp_service: Optional["ACPService"] = None,
        permission_broker: Optional["ACPPermissionBroker"] = None,
        delivery_callback: Optional[Callable[..., Any]] = None,
    ):
        """Initialize the ACP cron handler.

        Args:
            acp_service: The ACP service for processing messages.
            permission_broker: Permission broker for unattended mode.
            delivery_callback: Callback for delivering results to channels.
        """
        self._acp_service = acp_service
        self._permission_broker = permission_broker
        self._delivery_callback = delivery_callback

    @property
    def acp_service(self) -> Optional["ACPService"]:
        """Get the ACP service."""
        return self._acp_service

    @property
    def permission_broker(self) -> Optional["ACPPermissionBroker"]:
        """Get the permission broker."""
        return self._permission_broker

    def is_configured(self) -> bool:
        """Check if ACP cron handler is properly configured.

        Returns:
            True if ACP service is available, False otherwise.
        """
        return self._acp_service is not None

    async def execute(self, job: "CronJob") -> Optional[str]:
        """Execute a cron job through ACP backend.

        This method:
        1. Derives session key from cron job payload (channel:chat_id)
        2. Loads/creates an ACP session for that key
        3. Processes the message through ACP
        4. Delivers result back to channel if configured

        Args:
            job: The cron job to execute.

        Returns:
            The response content, or None if delivery is not requested.
        """
        if not self._acp_service:
            logger.warning("ACP cron handler called but no ACP service configured")
            return None

        # Derive session key from payload
        session_key = self._get_session_key(job)
        if not session_key:
            logger.warning("Cron job has no session key, skipping ACP execution")
            return None

        logger.info("ACP cron: processing job '{}' for session {}", job.name, session_key)

        try:
            # Load or create ACP session
            session_result = await self._acp_service.load_session(session_key)
            acp_session_id = session_result.get("acp_session_id")
            logger.debug("ACP cron: using session {} for {}", acp_session_id, session_key)

            # Process the message through ACP
            chunks = await self._acp_service.process_message(session_key, job.payload.message)

            # Collect response
            response_parts = []
            for chunk in chunks:
                if hasattr(chunk, "content") and chunk.content:
                    response_parts.append(chunk.content)

            response = "".join(response_parts)
            if not response:
                response = "ACP cron job completed."

            # Deliver result if requested
            if job.payload.deliver:
                await self._deliver_response(job, response)

            logger.info("ACP cron: job '{}' completed", job.name)
            return response

        except Exception as e:
            logger.error("ACP cron: job '{}' failed: {}", job.name, e)
            # Still try to deliver error
            if job.payload.deliver:
                await self._deliver_response(job, f"Cron error: {str(e)[:200]}")
            raise

    def _get_session_key(self, job: "CronJob") -> Optional[str]:
        """Derive session key from cron job payload.

        Args:
            job: The cron job.

        Returns:
            Session key in format "channel:chat_id", or None if invalid.
        """
        channel = job.payload.channel
        chat_id = job.payload.to

        if not channel or not chat_id:
            return None

        return f"{channel}:{chat_id}"

    async def _deliver_response(self, job: "CronJob", response: str) -> None:
        """Deliver response back to the originating channel.

        Args:
            job: The cron job.
            response: The response to deliver.
        """
        if self._delivery_callback:
            try:
                await self._delivery_callback(
                    response=response,
                    channel=job.payload.channel,
                    to=job.payload.to,
                )
            except Exception as e:
                logger.error("ACP cron: delivery failed: {}", e)
        else:
            # Default: log if no callback
            logger.info(
                "ACP cron: delivery requested but no callback configured (channel={}, to={})",
                job.payload.channel,
                job.payload.to,
            )


def create_acp_cron_handler(
    acp_service: Optional["ACPService"] = None,
    policy_default: str = "allow",
    delivery_callback: Optional[Callable[..., Any]] = None,
) -> ACPCronHandler:
    """Factory function to create an ACP cron handler with default configuration.

    Args:
        acp_service: The ACP service.
        policy_default: Default permission policy mode ("allow", "deny", or "ask").
        delivery_callback: Callback for delivering results.

    Returns:
        Configured ACPCronHandler instance.
    """
    from nanobot.acp.permissions import PermissionBrokerFactory
    from nanobot.acp.policy import UnattendedPermissionPolicy

    # Create unattended permission broker
    policy = UnattendedPermissionPolicy(default_mode=policy_default)
    permission_broker = PermissionBrokerFactory.create_unattended(policy=policy)

    return ACPCronHandler(
        acp_service=acp_service,
        permission_broker=permission_broker,
        delivery_callback=delivery_callback,
    )
