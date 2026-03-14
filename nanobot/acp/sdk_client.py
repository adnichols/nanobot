"""SDK transport adapter for ACP.

This module provides a high-level client wrapper around the agent-client-protocol
SDK, handling connection lifecycle, notification routing, and error mapping.

The SDKClient wraps the SDK's Connection class and provides a clean API for
interacting with ACP-compliant agents (like OpenCode).
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, cast

from acp import spawn_stdio_connection
from acp.connection import Connection
from acp.exceptions import RequestError

from nanobot.acp.interfaces import ACPCallbackRegistry, ACPSessionStore, ACPUpdateSink
from nanobot.acp.sdk_types import (
    from_sdk_initialize_response,
    from_sdk_notification,
    from_sdk_prompt_chunk,
    from_sdk_session_response,
    to_sdk_cancel_params,
    to_sdk_initialize_params,
    to_sdk_load_session_params,
    to_sdk_new_session_params,
    to_sdk_prompt_params,
)
from nanobot.acp.terminal import ACPInvalidTerminalError
from nanobot.acp.types import (
    ACPInitializeRequest,
    ACPStreamChunk,
    ACPStreamChunkType,
    ACPUpdateEvent,
)

logger = logging.getLogger(__name__)

StreamChunkCallback = Callable[[str], Awaitable[None]]


class SDKError(Exception):
    """Base exception for SDK-related errors."""

    pass


class SDKConnectionError(SDKError):
    """Raised when connection to the agent fails."""

    pass


class SDKTimedOutError(SDKError):
    """Raised when an operation times out."""

    pass


class SDKInitializationError(SDKError):
    """Raised when agent initialization fails."""

    pass


class SDKSessionError(SDKError):
    """Raised when session operations fail."""

    pass


class SDKPromptError(SDKError):
    """Raised when prompt operations fail."""

    pass


class SDKNotificationHandler:
    """Handler for SDK notifications that routes to nanobot callbacks."""

    def __init__(
        self,
        update_sink: Optional[ACPUpdateSink] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        permission_broker: Any = None,
        filesystem_handler: Any = None,
        terminal_manager: Any = None,
        connection: Any = None,
    ):
        """Initialize the notification handler.

        Args:
            update_sink: Sink for update events.
            callback_registry: Registry for permission callbacks.
            permission_broker: Broker for permission requests.
            filesystem_handler: Handler for filesystem operations.
            terminal_manager: Manager for terminal operations.
        """
        self._update_sink = update_sink
        self._callback_registry = callback_registry
        self._permission_broker = permission_broker
        self._filesystem_handler = filesystem_handler
        self._terminal_manager = terminal_manager
        self._connection = connection
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._stream_chunks: dict[str, list[ACPStreamChunk]] = {}
        self._stream_callbacks: dict[str, StreamChunkCallback] = {}
        self._available_commands: dict[str, list[dict[str, Any]]] = {}
        self._available_command_events: dict[str, asyncio.Event] = {}

    async def __call__(self, method: str, params: Any, is_notification: bool) -> Any | None:
        """Handle an incoming method call from the agent.

        Args:
            method: The ACP method name.
            params: The ACP payload.
            is_notification: Whether the method is a notification.
        """
        method, params = from_sdk_notification(method, params)
        logger.debug(f"Received notification: {method}")

        # Route based on method
        if method == "session/update":
            self._handle_available_commands_update(params)
            await self._record_stream_chunk(params)
            self._handle_session_update(params)
            return None
        elif method == "session/request_permission":
            if is_notification:
                asyncio.create_task(
                    self._handle_permission_request(params, respond_via_notification=True)
                )
                return None
            return await self._handle_permission_request(params)
        elif method == "fs/read_text_file":
            if is_notification:
                asyncio.create_task(self._handle_fs_read(params, respond_via_notification=True))
                return None
            return await self._handle_fs_read(params)
        elif method == "fs/write_text_file":
            if is_notification:
                asyncio.create_task(self._handle_fs_write(params, respond_via_notification=True))
                return None
            return await self._handle_fs_write(params)
        elif method == "terminal/create":
            if is_notification:
                asyncio.create_task(
                    self._handle_terminal_create(params, respond_via_notification=True)
                )
                return None
            return await self._handle_terminal_create(params)
        elif method == "terminal/output":
            if is_notification:
                asyncio.create_task(
                    self._handle_terminal_output(params, respond_via_notification=True)
                )
                return None
            return await self._handle_terminal_output(params)
        elif method == "terminal/wait_for_exit":
            if is_notification:
                asyncio.create_task(
                    self._handle_terminal_wait_for_exit(params, respond_via_notification=True)
                )
                return None
            return await self._handle_terminal_wait_for_exit(params)
        elif method == "terminal/kill":
            if is_notification:
                asyncio.create_task(
                    self._handle_terminal_kill(params, respond_via_notification=True)
                )
                return None
            return await self._handle_terminal_kill(params)
        elif method == "terminal/release":
            if is_notification:
                asyncio.create_task(
                    self._handle_terminal_release(params, respond_via_notification=True)
                )
                return None
            return await self._handle_terminal_release(params)
        else:
            logger.debug(f"Unhandled notification method: {method}")
            return None

    def bind_connection(self, connection: Any) -> None:
        """Attach the live SDK connection for callback round-trips."""
        self._connection = connection

    def begin_stream(self, session_id: str, on_chunk: StreamChunkCallback | None = None) -> None:
        """Reset buffered stream chunks for a prompt request."""
        self._stream_chunks[session_id] = []
        if on_chunk is None:
            self._stream_callbacks.pop(session_id, None)
        else:
            self._stream_callbacks[session_id] = on_chunk

    def clear_stream(self, session_id: str) -> None:
        """Discard buffered chunks and any live callback for a prompt request."""
        self._stream_callbacks.pop(session_id, None)
        self._stream_chunks.pop(session_id, None)

    def take_stream_chunks(self, session_id: str) -> list[ACPStreamChunk]:
        """Return buffered stream chunks for a completed prompt request."""
        self._stream_callbacks.pop(session_id, None)
        return self._stream_chunks.pop(session_id, [])

    def _handle_session_update(self, params: dict[str, Any]) -> None:
        """Handle session update notifications."""
        if self._update_sink is None:
            return

        event = self._convert_session_update(params)
        if event is None:
            return

        asyncio.create_task(self._update_sink.send_update(event))

    def _handle_available_commands_update(self, params: dict[str, Any]) -> None:
        """Capture available slash commands advertised by the ACP agent."""
        session_id = params.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        update = params.get("update", {})
        if not isinstance(update, dict):
            return

        session_update = update.get("session_update", {})
        kind = session_update.get("kind") if isinstance(session_update, dict) else None
        if kind not in {"available_commands", "available_commands_update"}:
            return

        raw_commands = update.get("available_commands")
        if not isinstance(raw_commands, list):
            return

        normalized: list[dict[str, Any]] = []
        for item in raw_commands:
            if not isinstance(item, dict):
                continue
            normalized.append(dict(item))

        self._available_commands[session_id] = normalized
        self._available_command_events.setdefault(session_id, asyncio.Event()).set()

    def available_commands_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return the last available-commands update for a session."""
        return [dict(item) for item in self._available_commands.get(session_id, [])]

    async def wait_for_available_commands(
        self,
        session_id: str,
        *,
        timeout: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Wait briefly for an available-commands update for a session."""
        existing = self.available_commands_for_session(session_id)
        if existing:
            return existing

        event = self._available_command_events.setdefault(session_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return self.available_commands_for_session(session_id)
        return self.available_commands_for_session(session_id)

    def _convert_session_update(self, params: dict[str, Any]) -> ACPUpdateEvent | None:
        """Convert a normalized session/update payload into an internal ACP event."""
        session_id = params.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None

        update = params.get("update", {})
        if not isinstance(update, dict):
            return None

        session_update = update.get("session_update", {})
        kind = session_update.get("kind") if isinstance(session_update, dict) else None
        if kind in {None, "agent_message_chunk"}:
            return None

        correlation_id = update.get("tool_call_id") or session_id
        timestamp = datetime.now(UTC)

        if kind == "agent_thought_chunk":
            thought = self._extract_text_content(update.get("content"))
            if thought is None:
                thought = str(session_update.get("thought") or update.get("thought") or "").strip()
            if not thought:
                return None
            return ACPUpdateEvent(
                event_type="agent_thought_chunk",
                timestamp=timestamp,
                payload={"session_id": session_id, "content": thought},
                correlation_id=correlation_id,
            )

        if kind in {"tool_call", "tool_call_update"}:
            tool_name = str(update.get("title") or update.get("kind") or "tool").strip() or "tool"
            tool_input = update.get("raw_input")
            if not isinstance(tool_input, dict):
                tool_input = {}
            content = (
                self._extract_text_content(update.get("content"))
                or str(update.get("raw_output") or "").strip()
            )
            status = str(update.get("status") or "pending")

            if status in {"completed", "failed"}:
                event_type = "tool_result" if content else "tool_use_end"
            else:
                event_type = "tool_use_start"

            payload = {
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "status": status,
                "tool_call_id": update.get("tool_call_id"),
            }
            if content:
                payload["content"] = content
            return ACPUpdateEvent(
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
                correlation_id=correlation_id,
            )

        content = self._extract_text_content(update.get("content"))
        if content:
            return ACPUpdateEvent(
                event_type="system_notice",
                timestamp=timestamp,
                payload={
                    "session_id": session_id,
                    "content": content,
                    "kind": kind,
                },
                correlation_id=correlation_id,
            )

        return ACPUpdateEvent(
            event_type="system_notice",
            timestamp=timestamp,
            payload={
                "session_id": session_id,
                "content": str(kind),
                "kind": kind,
            },
            correlation_id=correlation_id,
        )

    @staticmethod
    def _extract_text_content(content: Any) -> str | None:
        """Extract plain text from ACP content payloads when present."""
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            return None

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                nested = item.get("content") if item.get("type") == "content" else item
                if not isinstance(nested, dict) or nested.get("type") != "text":
                    continue
                text = nested.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            return "\n".join(parts) if parts else None

        if isinstance(content, str) and content.strip():
            return content.strip()

        return None

    async def _record_stream_chunk(self, params: dict[str, Any]) -> None:
        """Capture streamed assistant text from session/update notifications."""
        session_id = params.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        update = params.get("update", {})
        session_update = update.get("session_update", {})
        kind = session_update.get("kind") if isinstance(session_update, dict) else None
        if kind != "agent_message_chunk":
            return

        content = update.get("content", {})
        if not isinstance(content, dict) or content.get("type") != "text":
            return

        text = content.get("text")
        if not isinstance(text, str) or not text:
            return

        chunk = ACPStreamChunk(type=ACPStreamChunkType.CONTENT_DELTA, content=text)
        self._stream_chunks.setdefault(session_id, []).append(chunk)

        callback = self._stream_callbacks.get(session_id)
        if callback is not None:
            await callback(text)

    async def _send_callback_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a callback resolution back to the ACP agent when connected."""
        if self._connection is None:
            logger.warning("Callback result for %s dropped because no connection is bound", method)
            return

        await self._connection.send_notification(method, params)

    @staticmethod
    def _first_option_id(options: Any, kinds: tuple[str, ...]) -> str | None:
        if not isinstance(options, list):
            return None

        for option in options:
            if not isinstance(option, dict):
                continue
            kind = option.get("kind")
            option_id = option.get("optionId") or option.get("option_id")
            if kind in kinds and isinstance(option_id, str) and option_id:
                return option_id
        return None

    @classmethod
    def _permission_outcome(cls, granted: bool, options: Any) -> dict[str, Any]:
        """Map a nanobot permission decision onto ACP-style outcome metadata."""
        if granted:
            option_id = (
                cls._first_option_id(options, ("allow_once", "allow_always")) or "allow_once"
            )
            return {"outcome": "selected", "optionId": option_id}
        return {"outcome": "cancelled"}

    @staticmethod
    def _session_id_from_params(params: dict[str, Any], fallback: str | None = None) -> str:
        session_id = params.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
        return fallback or "unknown-session"

    @classmethod
    def _infer_filesystem_operation(cls, params: dict[str, Any], raw_input: dict[str, Any]) -> str:
        operation = params.get("operation") or raw_input.get("operation")
        if isinstance(operation, str) and operation:
            return operation
        if any(key in raw_input for key in ("content", "new_text", "newText")):
            return "write"
        return "read"

    @classmethod
    def _build_permission_callback(
        cls,
        *,
        permission_type: str,
        params: dict[str, Any],
        raw_input: dict[str, Any],
        resource: str,
    ) -> Any:
        from nanobot.acp.types import ACPFilesystemCallback, ACPTerminalCallback

        if permission_type == "filesystem":
            path = str(raw_input.get("path") or resource)
            return ACPFilesystemCallback(
                operation=cls._infer_filesystem_operation(params, raw_input),
                path=path,
                content=raw_input.get("content")
                or raw_input.get("new_text")
                or raw_input.get("newText"),
                metadata=params,
            )

        if permission_type == "terminal":
            command = raw_input.get("command") or resource
            if not isinstance(command, str):
                command = str(command)
            args = raw_input.get("args")
            command_parts = [command] if command else []
            if isinstance(args, list):
                command_parts.extend(str(arg) for arg in args)
            return ACPTerminalCallback(
                command=" ".join(command_parts),
                working_directory=raw_input.get("cwd") or raw_input.get("working_directory"),
                environment=cls._normalize_terminal_environment(
                    raw_input.get("env") or raw_input.get("environment")
                ),
                timeout=raw_input.get("timeout"),
            )

        return None

    async def _emit_decision_update(
        self,
        *,
        session_id: str,
        correlation_id: str | None,
        granted: bool,
        reason: str,
    ) -> None:
        if self._update_sink is None:
            return

        await self._update_sink.send_update(
            ACPUpdateEvent(
                event_type="permission_decision",
                timestamp=datetime.now(UTC),
                payload={
                    "session_id": session_id,
                    "granted": granted,
                    "reason": reason,
                },
                correlation_id=correlation_id,
            )
        )

    async def _request_callback_permission(
        self,
        *,
        request_id: str,
        session_id: str,
        permission_type: str,
        description: str,
        resource: str,
        callback: Any,
        correlation_id: str | None,
    ) -> Any | None:
        """Resolve permission policy for direct filesystem/terminal callbacks."""
        if self._permission_broker is None:
            return None

        from nanobot.acp.types import ACPPermissionRequest

        if self._update_sink is not None:
            await self._update_sink.send_update(
                ACPUpdateEvent(
                    event_type="permission_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": session_id,
                        "permission_type": permission_type,
                        "description": description,
                        "resource": resource,
                    },
                    correlation_id=correlation_id,
                )
            )

        decision = await self._permission_broker.request_permission(
            ACPPermissionRequest(
                id=request_id,
                permission_type=permission_type,
                description=description,
                resource=resource,
                callback=callback,
                correlation_id=correlation_id,
            )
        )

        await self._emit_decision_update(
            session_id=session_id,
            correlation_id=correlation_id,
            granted=decision.granted,
            reason=decision.reason or "",
        )
        return decision

    async def _run_filesystem_callback(
        self, callback: Any
    ) -> tuple[Any | None, dict[str, Any] | None]:
        if self._filesystem_handler is None:
            logger.warning("Filesystem request received but no handler configured")
            return (None, None)

        if hasattr(self._filesystem_handler, "execute_callback"):
            return await self._filesystem_handler.execute_callback(callback)

        if hasattr(self._filesystem_handler, "handle_filesystem_callback"):
            decision = await self._filesystem_handler.handle_filesystem_callback(callback)
            return (decision, self._fallback_filesystem_response(callback, decision))
        if hasattr(self._filesystem_handler, "handle_filesystem"):
            decision = await self._filesystem_handler.handle_filesystem(callback)
            return (decision, self._fallback_filesystem_response(callback, decision))
        if callable(self._filesystem_handler):
            handler = cast(Callable[[Any], Awaitable[Any]], self._filesystem_handler)
            decision = await handler(callback)
            return (decision, self._fallback_filesystem_response(callback, decision))

        logger.warning("Filesystem handler does not expose a supported callback surface")
        return (None, None)

    @staticmethod
    def _fallback_filesystem_response(callback: Any, decision: Any) -> dict[str, Any] | None:
        if decision is None or not getattr(decision, "granted", False):
            return None
        if getattr(callback, "operation", None) == "read":
            return {"content": str(decision.reason or "")}
        return {}

    @staticmethod
    async def _maybe_send_notification(
        *,
        respond_via_notification: bool,
        send: Callable[[str, dict[str, Any]], Awaitable[None]],
        method: str,
        payload: dict[str, Any],
    ) -> None:
        if respond_via_notification:
            await send(method, payload)

    @staticmethod
    def _raise_callback_denial(reason: str, **data: Any) -> None:
        payload = {key: value for key, value in data.items() if value is not None}
        payload["reason"] = reason
        raise RequestError.invalid_params(payload)

    @staticmethod
    def _terminal_exit_status_payload(exit_code: int | None) -> dict[str, Any] | None:
        if exit_code is None:
            return None
        if exit_code < 0:
            try:
                signal_name = signal.Signals(abs(exit_code)).name
            except ValueError:
                signal_name = str(abs(exit_code))
            return {"signal": signal_name}
        return {"exitCode": exit_code}

    @staticmethod
    def _terminal_error_payload(
        terminal_id: str,
        operation: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "terminalId": terminal_id,
            "operation": operation,
            "reason": reason,
        }

    async def _handle_terminal_error(
        self,
        *,
        method: str,
        terminal_id: str,
        operation: str,
        error: Exception,
        respond_via_notification: bool,
    ) -> None:
        payload = self._terminal_error_payload(terminal_id, operation, str(error))
        if respond_via_notification:
            await self._send_callback_notification(method, {"error": payload})
            return
        raise RequestError.invalid_params(payload)

    @staticmethod
    def _normalize_terminal_environment(environment: Any) -> dict[str, str]:
        if isinstance(environment, dict):
            return {
                str(name): str(value)
                for name, value in environment.items()
                if isinstance(name, str) and value is not None
            }

        if not isinstance(environment, list):
            return {}

        env: dict[str, str] = {}
        for item in environment:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and value is not None:
                env[name] = str(value)
        return env

    async def _handle_permission_request(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        """Handle permission request notifications."""
        if self._permission_broker is None:
            logger.warning("Permission request received but no broker configured")
            return None

        # Extract permission request details
        from nanobot.acp.types import ACPPermissionRequest

        tool_call = params.get("tool_call") or params.get("toolCall") or {}
        if not isinstance(tool_call, dict):
            tool_call = {}

        request_id = params.get("request_id") or params.get("id") or "unknown"
        permission_type = params.get("permission_type") or tool_call.get("kind") or "unknown"
        description = params.get("description") or tool_call.get("title") or ""
        raw_input = tool_call.get("raw_input") or tool_call.get("rawInput") or {}
        if not isinstance(raw_input, dict):
            raw_input = {}
        resource = params.get("resource") or raw_input.get("path") or raw_input.get("command") or ""
        correlation_id = (
            tool_call.get("tool_call_id") or tool_call.get("toolCallId") or params.get("session_id")
        )

        request = ACPPermissionRequest(
            id=request_id,
            permission_type=permission_type,
            description=description,
            resource=resource,
            callback=self._build_permission_callback(
                permission_type=permission_type,
                params=params,
                raw_input=raw_input,
                resource=resource,
            ),
            correlation_id=correlation_id,
        )

        session_id = self._session_id_from_params(params, fallback=correlation_id)

        if self._update_sink is not None:
            await self._update_sink.send_update(
                ACPUpdateEvent(
                    event_type="permission_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "session_id": session_id,
                        "permission_type": permission_type,
                        "description": description,
                        "resource": resource,
                    },
                    correlation_id=correlation_id,
                )
            )

        decision = await self._permission_broker.request_permission(request)

        reason = decision.reason or ""
        await self._emit_decision_update(
            session_id=session_id,
            correlation_id=correlation_id,
            granted=decision.granted,
            reason=reason,
        )

        response = {
            "outcome": self._permission_outcome(decision.granted, params.get("options")),
        }
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="session/request_permission",
            payload=response,
        )

        logger.debug(f"Permission decision: {decision.granted} - {decision.reason}")
        return response

    async def _handle_fs_read(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        """Handle filesystem read request notifications."""
        from nanobot.acp.types import ACPFilesystemCallback

        callback = ACPFilesystemCallback(
            operation="read",
            path=params.get("path", ""),
            metadata=params,
        )

        session_id = self._session_id_from_params(params)
        correlation_id = str(params.get("request_id") or session_id)
        reason = ""
        broker_decision = await self._request_callback_permission(
            request_id=correlation_id,
            session_id=session_id,
            permission_type="filesystem",
            description=f"Read {callback.path}",
            resource=callback.path,
            callback=callback,
            correlation_id=correlation_id,
        )
        if broker_decision is not None and not broker_decision.granted:
            reason = broker_decision.reason or "Denied"
            if respond_via_notification:
                await self._send_callback_notification(
                    "fs/read_text_file",
                    {"error": {"reason": reason, "path": callback.path}},
                )
                return None
            self._raise_callback_denial(reason, path=callback.path, operation=callback.operation)

        decision, response_payload = await self._run_filesystem_callback(callback)
        if decision is None:
            return None

        reason = decision.reason or ""

        if broker_decision is None:
            session_id = self._session_id_from_params(params, fallback=decision.request_id)
            await self._emit_decision_update(
                session_id=session_id,
                correlation_id=decision.request_id or session_id,
                granted=decision.granted,
                reason=reason,
            )

        if not decision.granted:
            if respond_via_notification:
                await self._send_callback_notification(
                    "fs/read_text_file",
                    {"error": {"reason": reason, "path": callback.path}},
                )
                return None
            self._raise_callback_denial(reason, path=callback.path, operation=callback.operation)

        response = response_payload or {"content": ""}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="fs/read_text_file",
            payload=response,
        )
        logger.debug(f"Filesystem decision: {decision.granted} - {decision.reason}")
        return response

    async def _handle_fs_write(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        """Handle filesystem write request notifications."""
        from nanobot.acp.types import ACPFilesystemCallback

        callback = ACPFilesystemCallback(
            operation="write",
            path=params.get("path", ""),
            content=params.get("content"),
            metadata=params,
        )

        session_id = self._session_id_from_params(params)
        correlation_id = str(params.get("request_id") or session_id)
        reason = ""
        broker_decision = await self._request_callback_permission(
            request_id=correlation_id,
            session_id=session_id,
            permission_type="filesystem",
            description=f"Write {callback.path}",
            resource=callback.path,
            callback=callback,
            correlation_id=correlation_id,
        )
        if broker_decision is not None and not broker_decision.granted:
            reason = broker_decision.reason or "Denied"
            if respond_via_notification:
                await self._send_callback_notification(
                    "fs/write_text_file",
                    {"error": {"reason": reason, "path": callback.path}},
                )
                return None
            self._raise_callback_denial(reason, path=callback.path, operation=callback.operation)

        decision, response_payload = await self._run_filesystem_callback(callback)
        if decision is None:
            return None

        reason = decision.reason or ""

        if broker_decision is None:
            session_id = self._session_id_from_params(params, fallback=decision.request_id)
            await self._emit_decision_update(
                session_id=session_id,
                correlation_id=decision.request_id or session_id,
                granted=decision.granted,
                reason=reason,
            )

        if not decision.granted:
            if respond_via_notification:
                await self._send_callback_notification(
                    "fs/write_text_file",
                    {"error": {"reason": reason, "path": callback.path}},
                )
                return None
            self._raise_callback_denial(reason, path=callback.path, operation=callback.operation)

        response = response_payload or {}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="fs/write_text_file",
            payload=response,
        )
        logger.debug(f"Filesystem decision: {decision.granted} - {decision.reason}")
        return response

    async def _handle_terminal_create(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        """Handle terminal create request notifications."""
        if self._terminal_manager is None:
            logger.warning("Terminal create request but no manager configured")
            return None

        from nanobot.acp.types import ACPTerminalCallback

        command = params.get("command", "")
        args = params.get("args")
        command_parts = [str(command)] if isinstance(command, str) and command else []
        if isinstance(args, list):
            command_parts.extend(str(arg) for arg in args)

        callback = ACPTerminalCallback(
            command=" ".join(command_parts),
            working_directory=params.get("working_directory") or params.get("cwd"),
            environment=self._normalize_terminal_environment(
                params.get("environment") or params.get("env")
            ),
            timeout=params.get("timeout"),
        )

        session_id = self._session_id_from_params(params)
        correlation_id = str(params.get("request_id") or session_id)
        broker_decision = await self._request_callback_permission(
            request_id=correlation_id,
            session_id=session_id,
            permission_type="terminal",
            description=f"Run {callback.command}",
            resource=callback.command,
            callback=callback,
            correlation_id=correlation_id,
        )
        if broker_decision is not None and not broker_decision.granted:
            reason = broker_decision.reason or "Denied"
            if respond_via_notification:
                await self._send_callback_notification(
                    "terminal/create",
                    {"error": {"reason": reason, "command": callback.command}},
                )
                return None
            self._raise_callback_denial(reason, command=callback.command)

        try:
            terminal_id = await self._terminal_manager.create(
                command_parts,
                working_directory=callback.working_directory,
                environment=callback.environment,
                output_byte_limit=params.get("output_byte_limit") or params.get("outputByteLimit"),
                permission_checked=broker_decision is not None,
            )
            granted = True
            reason = f"Created terminal {terminal_id}"
        except PermissionError as exc:
            terminal_id = None
            granted = False
            reason = str(exc)
        except Exception as exc:
            terminal_id = None
            granted = False
            reason = f"Terminal error: {exc}"

        if broker_decision is None:
            await self._emit_decision_update(
                session_id=session_id,
                correlation_id=correlation_id,
                granted=granted,
                reason=reason,
            )

        if terminal_id is None:
            if respond_via_notification:
                await self._send_callback_notification(
                    "terminal/create",
                    {"error": {"reason": reason, "command": callback.command}},
                )
                return None
            self._raise_callback_denial(reason, command=callback.command)

        response = {"terminalId": terminal_id}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="terminal/create",
            payload=response,
        )
        logger.debug(f"Terminal create request: {callback.command}")
        return response

    async def _handle_terminal_output(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        if self._terminal_manager is None:
            logger.warning("Terminal output request but no manager configured")
            return None

        terminal_id = str(params.get("terminal_id") or params.get("terminalId") or "")
        try:
            output = await self._terminal_manager.output(terminal_id)
        except (ACPInvalidTerminalError, asyncio.TimeoutError) as exc:
            await self._handle_terminal_error(
                method="terminal/output",
                terminal_id=terminal_id,
                operation="output",
                error=exc,
                respond_via_notification=respond_via_notification,
            )
            return None
        exit_status = None
        terminals = getattr(self._terminal_manager, "_terminals", None)
        terminal = terminals.get(terminal_id) if isinstance(terminals, dict) else None
        truncated = False
        if terminal is not None:
            exit_status = self._terminal_exit_status_payload(getattr(terminal, "exit_code", None))
            truncated = bool(getattr(terminal, "output_truncated", False))

        response = {
            "output": output,
            "truncated": truncated,
        }
        if exit_status is not None:
            response["exitStatus"] = exit_status

        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="terminal/output",
            payload=response,
        )
        return response

    async def _handle_terminal_wait_for_exit(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        if self._terminal_manager is None:
            logger.warning("Terminal wait request but no manager configured")
            return None

        terminal_id = str(params.get("terminal_id") or params.get("terminalId") or "")
        try:
            exit_code = await self._terminal_manager.wait_for_exit(terminal_id)
        except (ACPInvalidTerminalError, asyncio.TimeoutError) as exc:
            await self._handle_terminal_error(
                method="terminal/wait_for_exit",
                terminal_id=terminal_id,
                operation="wait_for_exit",
                error=exc,
                respond_via_notification=respond_via_notification,
            )
            return None
        response = self._terminal_exit_status_payload(exit_code) or {}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="terminal/wait_for_exit",
            payload=response,
        )
        return response

    async def _handle_terminal_kill(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        if self._terminal_manager is None:
            logger.warning("Terminal kill request but no manager configured")
            return None

        terminal_id = str(params.get("terminal_id") or params.get("terminalId") or "")
        try:
            await self._terminal_manager.kill(terminal_id)
        except (ACPInvalidTerminalError, asyncio.TimeoutError) as exc:
            await self._handle_terminal_error(
                method="terminal/kill",
                terminal_id=terminal_id,
                operation="kill",
                error=exc,
                respond_via_notification=respond_via_notification,
            )
            return None
        response: dict[str, Any] = {}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="terminal/kill",
            payload=response,
        )
        return response

    async def _handle_terminal_release(
        self,
        params: dict[str, Any],
        *,
        respond_via_notification: bool = False,
    ) -> dict[str, Any] | None:
        if self._terminal_manager is None:
            logger.warning("Terminal release request but no manager configured")
            return None

        terminal_id = str(params.get("terminal_id") or params.get("terminalId") or "")
        try:
            await self._terminal_manager.release(terminal_id)
        except (ACPInvalidTerminalError, asyncio.TimeoutError) as exc:
            await self._handle_terminal_error(
                method="terminal/release",
                terminal_id=terminal_id,
                operation="release",
                error=exc,
                respond_via_notification=respond_via_notification,
            )
            return None
        response: dict[str, Any] = {}
        await self._maybe_send_notification(
            respond_via_notification=respond_via_notification,
            send=self._send_callback_notification,
            method="terminal/release",
            payload=response,
        )
        return response


class SDKClient:
    """SDK-based ACP client.

    Provides a high-level API for interacting with ACP-compliant agents
    using the official agent-client-protocol SDK.
    """

    _MODEL_SWITCH_SETTLE_SECONDS = 0.1

    def __init__(
        self,
        agent_path: Optional[str] = None,
        model: Optional[str] = None,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        session_store: Optional[ACPSessionStore] = None,
        callback_registry: Optional[ACPCallbackRegistry] = None,
        update_sink: Optional[ACPUpdateSink] = None,
        permission_broker: Any = None,
        filesystem_handler: Any = None,
        terminal_manager: Any = None,
    ):
        """Initialize the SDK client.

        Args:
            agent_path: Path to the ACP agent executable (e.g., "opencode").
            model: Preferred ACP session model (e.g., "openai/gpt-5.4").
            args: Arguments to pass to the agent (e.g., ["acp"]).
            env: Environment variables for the agent process.
            cwd: Working directory for the agent process.
            session_store: Optional session store for persistence.
            callback_registry: Registry for permission callbacks.
            update_sink: Sink for update events.
            permission_broker: Broker for permission requests.
            filesystem_handler: Handler for filesystem operations.
            terminal_manager: Manager for terminal operations.
        """
        self.agent_path = agent_path
        self.model = model
        self.args = args or []
        self.env = env
        self.cwd = cwd

        self._session_store = session_store
        self._callback_registry = callback_registry
        self._update_sink = update_sink
        self._permission_broker = permission_broker
        self._filesystem_handler = filesystem_handler
        self._terminal_manager = terminal_manager

        self._connection: Optional[Connection] = None
        self._process: Optional[Any] = None
        self._notification_handler: Optional[SDKNotificationHandler] = None
        self._current_session_id: Optional[str] = None
        self._capabilities: Optional[dict[str, Any]] = None
        self._initialized = False
        self._conn_context: Optional[Any] = None
        self._model_settle_deadline: Optional[float] = None

    @property
    def is_initialized(self) -> bool:
        """Check if the client is initialized."""
        return self._initialized

    @property
    def current_session_id(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session_id

    @property
    def capabilities(self) -> Optional[dict[str, Any]]:
        """Get the agent capabilities."""
        return self._capabilities

    def set_notification_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Set a custom notification handler.

        Args:
            handler: Function to call with (method, params) on notifications.
        """

        # Wrap the handler for SDK notifications
        def sdk_handler(notification: Any) -> None:
            method, params = from_sdk_notification(notification)
            handler(method, params)

        self._custom_notification_handler = sdk_handler

    async def initialize(self, session_id: Optional[str] = None) -> dict[str, Any]:
        """Initialize the client and agent.

        Args:
            session_id: Optional session ID to use.

        Returns:
            Dict containing initialization status and capabilities.

        Raises:
            SDKConnectionError: If connection to the agent fails.
            SDKInitializationError: If agent initialization fails.
        """
        if self._initialized:
            logger.warning("Client already initialized")
            return {
                "status": "already_initialized",
                "capabilities": self._capabilities,
            }

        if self.agent_path is None:
            # No agent path - just mark as initialized for testing
            self._initialized = True
            return {
                "status": "mock_initialized",
                "capabilities": {},
            }

        try:
            # Build the command
            command = [self.agent_path] + self.args

            # Create notification handler
            self._notification_handler = SDKNotificationHandler(
                update_sink=self._update_sink,
                callback_registry=self._callback_registry,
                permission_broker=self._permission_broker,
                filesystem_handler=self._filesystem_handler,
                terminal_manager=self._terminal_manager,
            )

            # Spawn the connection
            self._connection, self._process = await self._spawn_connection(
                command=command,
                handler=self._notification_handler,
            )
            self._notification_handler.bind_connection(self._connection)

            # Send initialize request
            init_params = to_sdk_initialize_params(
                ACPInitializeRequest(
                    session_id=session_id or "default-session",
                    system_prompt="You are a helpful AI assistant.",
                )
            )
            init_params["clientCapabilities"] = self._client_capabilities()

            response = await self._connection.send_request(
                "initialize",
                init_params,
            )

            # Parse the response
            result = from_sdk_initialize_response(response)

            self._capabilities = result.get("capabilities", {})
            self._initialized = True

            return {
                "status": "initialized",
                "capabilities": self._capabilities,
            }

        except FileNotFoundError as e:
            raise SDKConnectionError(f"Agent not found: {self.agent_path}") from e
        except Exception as e:
            raise SDKInitializationError(f"Initialization failed: {e}") from e

    async def _spawn_connection(
        self,
        command: list[str],
        handler: Callable[[str, Any, bool], Awaitable[Any | None]],
    ) -> tuple[Connection, Any]:
        """Spawn the stdio connection to the agent.

        Args:
            command: Command to spawn.
            handler: Notification handler.

        Returns:
            Tuple of (Connection, process).

        Raises:
            SDKConnectionError: If spawning fails.
        """
        try:
            # Get the async iterator from spawn_stdio_connection
            # Note: args must be passed as positional varargs, not keyword argument
            conn_iter = spawn_stdio_connection(
                handler,
                command[0],
                *command[1:],
                env=self.env,
                cwd=self.cwd,
            )
            # Enter the context to get connection and process
            connection, process = await conn_iter.__aenter__()
            # Store the iterator for later cleanup
            self._conn_context = conn_iter
            return (connection, process)
        except Exception as e:
            raise SDKConnectionError(f"Failed to spawn agent: {e}") from e

    async def new_session(self) -> dict[str, Any]:
        """Create a new ACP session.

        Returns:
            Dict containing the new session ID.

        Raises:
            SDKConnectionError: If not connected.
            SDKSessionError: If session creation fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        # Test mode: create in-memory session when no agent_path
        if self._connection is None:
            session_id = f"mock-session-{asyncio.get_event_loop().time():.0f}"
            self._current_session_id = session_id
            return {
                "session_id": session_id,
                "status": "created",
                "available_commands": [],
            }

        try:
            params = to_sdk_new_session_params(self._session_cwd())

            response = await self._connection.send_request(
                "session/new",
                params,
            )

            result = from_sdk_session_response(response)
            self._current_session_id = result.get("session_id")
            await self._attach_available_commands(result)

            return result

        except Exception as e:
            raise SDKSessionError(f"Failed to create session: {e}") from e

    async def load_session(self, session_id: str) -> dict[str, Any]:
        """Load an existing ACP session.

        Args:
            session_id: The session ID to load.

        Returns:
            Dict containing session status and data.

        Raises:
            SDKConnectionError: If not connected.
            SDKSessionError: If session loading fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        # Test mode: return mock session when no agent_path
        if self._connection is None:
            self._current_session_id = session_id
            return {
                "session_id": session_id,
                "status": "loaded",
                "available_commands": [],
                "session": {
                    "id": session_id,
                    "state": {},
                    "messages": [],
                },
            }

        try:
            params = to_sdk_load_session_params(session_id, self._session_cwd())

            response = await self._connection.send_request(
                "session/load",
                params,
            )

            result = from_sdk_session_response(response)
            self._current_session_id = session_id
            await self._attach_available_commands(result)

            return result

        except Exception as e:
            raise SDKSessionError(f"Failed to load session: {e}") from e

    async def prompt(
        self,
        content: str,
        session_id: Optional[str] = None,
        on_chunk: StreamChunkCallback | None = None,
    ) -> list[ACPStreamChunk]:
        """Send a prompt to the ACP agent.

        Args:
            content: The prompt content.
            session_id: Optional session ID (uses current session if not provided).
            on_chunk: Optional callback invoked for each live text chunk.

        Returns:
            List of stream chunks from the agent.

        Raises:
            SDKConnectionError: If not connected.
            SDKPromptError: If prompt fails.
        """
        if not self._initialized:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        target_session = session_id or self._current_session_id
        if not target_session:
            raise SDKPromptError(
                "No session ID available. Call new_session() or load_session() first."
            )

        # Test mode: return mock response when no agent_path
        if self._connection is None:
            chunk = ACPStreamChunk(
                type=ACPStreamChunkType.CONTENT_DELTA,
                content=f"Mock response to: {content}",
            )
            if on_chunk is not None and chunk.content:
                await on_chunk(chunk.content)
            return [chunk]

        try:
            await self._wait_for_model_settle()
            params = to_sdk_prompt_params(content, target_session)
            if self._notification_handler is not None:
                self._notification_handler.begin_stream(target_session, on_chunk=on_chunk)

            # Send the prompt request
            response = await self._connection.send_request(
                "session/prompt",
                params,
            )

            streamed_chunks: list[ACPStreamChunk] = []
            if self._notification_handler is not None:
                streamed_chunks = self._notification_handler.take_stream_chunks(target_session)

            return streamed_chunks + self._prompt_response_to_chunks(response)
        except Exception as e:
            if self._notification_handler is not None:
                self._notification_handler.clear_stream(target_session)
            raise SDKPromptError(f"Prompt failed: {e}") from e

    async def set_model(self, model: str, session_id: Optional[str] = None) -> None:
        """Set the active model for an ACP session."""
        if not self._initialized or self._connection is None:
            raise SDKConnectionError("Client not initialized. Call initialize() first.")

        target_session = session_id or self._current_session_id
        if not target_session:
            raise SDKSessionError(
                "No session ID available. Call new_session() or load_session() first."
            )

        try:
            await self._connection.send_request(
                "session/set_model",
                {
                    "sessionId": target_session,
                    "modelId": model,
                },
            )
            self._model_settle_deadline = (
                asyncio.get_running_loop().time() + self._MODEL_SWITCH_SETTLE_SECONDS
            )
        except Exception as e:
            raise SDKSessionError(f"Failed to set session model: {e}") from e

    async def cancel(self, session_id: Optional[str] = None) -> None:
        """Cancel an ongoing prompt operation.

        Args:
            session_id: Optional session ID (uses current session if not provided).

        Raises:
            SDKConnectionError: If not connected.
        """
        if not self._initialized or self._connection is None:
            # Not connected - nothing to cancel
            return

        target_session = session_id or self._current_session_id
        if not target_session:
            logger.warning("No session to cancel")
            return

        try:
            params = to_sdk_cancel_params(target_session)

            await self._connection.send_notification(
                "session/cancel",
                params,
            )

        except Exception as e:
            logger.warning(f"Cancel failed: {e}")

    def current_available_commands(self, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Return cached ACP slash commands for the current or provided session."""
        target_session = session_id or self._current_session_id
        if not target_session or self._notification_handler is None:
            return []
        return self._notification_handler.available_commands_for_session(target_session)

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        # Exit the connection context if it exists
        if self._conn_context is not None:
            try:
                await self._conn_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing connection context: {e}")
            self._conn_context = None

        self._connection = None
        self._process = None
        self._initialized = False
        self._current_session_id = None

    # Alias for compatibility with old ACPClient API
    async def shutdown(self) -> None:
        """Shutdown the client (alias for close())."""
        await self.close()

    async def _attach_available_commands(self, result: dict[str, Any]) -> None:
        """Attach advertised ACP slash commands to a session result when available."""
        session_id = result.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        handler = self._notification_handler
        if handler is None:
            return

        commands = await handler.wait_for_available_commands(session_id)
        result["available_commands"] = commands

    def subscribe_updates(self, sink: ACPUpdateSink) -> None:
        """Subscribe to update events.

        Args:
            sink: The update sink to receive events.
        """
        self._update_sink = sink
        if self._notification_handler is not None:
            self._notification_handler._update_sink = sink

    def clear_update_subscription(self) -> None:
        """Clear any update sink currently attached to this client."""
        self._update_sink = None
        if self._notification_handler is not None:
            self._notification_handler._update_sink = None

    def register_filesystem_callback(self, handler: Any) -> None:
        """Register a filesystem permission handler.

        Args:
            handler: Async handler for filesystem callbacks.
        """
        # Store the handler for notification routing
        self._filesystem_handler = handler
        if self._notification_handler is not None:
            self._notification_handler._filesystem_handler = handler

    def register_terminal_callback(self, handler: Any) -> None:
        """Register a terminal permission handler.

        Args:
            handler: Async handler for terminal callbacks.
        """
        # Store the handler for notification routing
        self._terminal_manager = handler
        if self._notification_handler is not None:
            self._notification_handler._terminal_manager = handler

    def _session_cwd(self) -> str:
        """Return the cwd to send in ACP session requests."""
        return self.cwd or str(Path.cwd())

    def _client_capabilities(self) -> dict[str, Any]:
        """Advertise ACP client features backed by live nanobot handlers."""
        capabilities: dict[str, Any] = {}
        if self._filesystem_handler is not None:
            capabilities["fs"] = {
                "readTextFile": True,
                "writeTextFile": True,
            }
        if self._terminal_manager is not None:
            capabilities["terminal"] = True
        return capabilities

    def _prompt_response_to_chunks(self, response: Any) -> list[ACPStreamChunk]:
        """Normalize an ACP prompt response to nanobot stream chunks."""
        parsed = from_sdk_prompt_chunk(response)
        content = parsed.get("content")
        if isinstance(content, str) and content:
            return [ACPStreamChunk(type=ACPStreamChunkType.CONTENT_DELTA, content=content)]
        return []

    async def _wait_for_model_settle(self) -> None:
        """Wait briefly after a session model switch before prompting."""
        if self._model_settle_deadline is None:
            return

        remaining = self._model_settle_deadline - asyncio.get_running_loop().time()
        self._model_settle_deadline = None
        if remaining > 0:
            await asyncio.sleep(remaining)
