"""Type conversions between nanobot domain types and SDK schema types.

This module provides functions to convert nanobot's internal domain types
to the schema types expected by the agent-client-protocol SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from acp import schema

    from nanobot.acp.types import (
        ACPInitializeRequest,
    )


def to_sdk_initialize_params(
    request: "ACPInitializeRequest",
) -> "schema.InitializeRequest":
    """Convert nanobot's ACPInitializeRequest to SDK InitializeRequest.

    Args:
        request: Nanobot's initialize request.

    Returns:
        SDK schema InitializeRequest ready for sending.
    """
    from acp import schema

    # Build client capabilities
    client_capabilities = schema.ClientCapabilities(
        fs=None,
        terminal=False,
    )

    # Build client info
    client_info = schema.Implementation(
        name="nanobot",
        version="0.1.0",
    )

    # Build the SDK InitializeRequest
    return schema.InitializeRequest(
        protocol_version=1,
        client_capabilities=client_capabilities,
        client_info=client_info,
    )


def to_sdk_new_session_params(
    session_id: str,
) -> "schema.NewSessionRequest":
    """Convert session ID to SDK NewSessionRequest.

    Args:
        session_id: The session ID to create.

    Returns:
        SDK schema NewSessionRequest ready for sending.
    """
    from acp import schema

    # NewSessionRequest expects cwd and mcp_servers
    return schema.NewSessionRequest(
        cwd="",
        mcp_servers=[],
    )


def to_sdk_prompt_params(
    content: str,
    session_id: str,
) -> "schema.PromptRequest":
    """Convert nanobot's prompt request to SDK PromptRequest.

    Args:
        content: The prompt content.
        session_id: The session ID to send the prompt to.

    Returns:
        SDK schema PromptRequest ready for sending.
    """
    from acp import schema

    # Build the prompt with text content
    prompt = [
        schema.TextContentBlock(
            type="text",
            text=content,
        )
    ]

    return schema.PromptRequest(
        session_id=session_id,
        prompt=prompt,
    )


def to_sdk_load_session_params(
    session_id: str,
) -> "schema.LoadSessionRequest":
    """Convert session ID to SDK LoadSessionRequest.

    Args:
        session_id: The session ID to load.

    Returns:
        SDK schema LoadSessionRequest ready for sending.
    """
    from acp import schema

    return schema.LoadSessionRequest(
        session_id=session_id,
    )


def to_sdk_cancel_params(
    session_id: str,
    request_id: Optional[str | int] = None,
) -> "schema.CancelRequestNotification":
    """Convert nanobot's cancel request to SDK CancelRequestNotification.

    Args:
        session_id: The session ID to cancel.
        request_id: Optional request ID to cancel specific operation.

    Returns:
        SDK schema CancelRequestNotification ready for sending.
    """
    from acp import schema

    return schema.CancelRequestNotification(
        session_id=session_id,
        requestId=request_id,
    )


def from_sdk_initialize_response(response: Any) -> dict[str, Any]:
    """Convert SDK initialize response to nanobot dict format.

    Args:
        response: SDK InitializeResponse.

    Returns:
        Dict with agent info and capabilities.
    """
    result: dict[str, Any] = {}

    if hasattr(response, "protocol_version"):
        result["protocol_version"] = response.protocol_version

    if hasattr(response, "agent_info"):
        result["agent_info"] = _extract_agent_info(response.agent_info)

    if hasattr(response, "capabilities"):
        result["capabilities"] = _extract_capabilities(response.capabilities)

    return result


def from_sdk_session_response(response: Any) -> dict[str, Any]:
    """Convert SDK session response to nanobot dict format.

    Args:
        response: SDK session response (NewSessionResponse or LoadSessionResponse).

    Returns:
        Dict with session_id and optional session data.
    """
    result: dict[str, Any] = {}

    if hasattr(response, "session_id"):
        result["session_id"] = response.session_id

    if hasattr(response, "session"):
        result["session"] = _extract_session_data(response.session)

    return result


def from_sdk_prompt_chunk(chunk: Any) -> dict[str, Any]:
    """Convert SDK prompt response chunk to nanobot stream chunk format.

    Args:
        chunk: SDK response chunk.

    Returns:
        Dict with chunk data for nanobot's stream handling.
    """
    result: dict[str, Any] = {}

    # Handle different chunk types from SDK
    if hasattr(chunk, "session_id"):
        result["session_id"] = chunk.session_id

    if hasattr(chunk, "message"):
        result["message"] = _extract_message_chunk(chunk.message)

    if hasattr(chunk, "usage"):
        result["usage"] = _extract_usage(chunk.usage)

    return result


def from_sdk_notification(notification: Any) -> tuple[str, dict[str, Any]]:
    """Convert SDK notification to method and params for routing.

    Args:
        notification: SDK notification.

    Returns:
        Tuple of (method, params dict) for routing to appropriate handler.
    """
    method = getattr(notification, "method", "unknown")
    params = getattr(notification, "params", {})

    # Extract params into dict
    params_dict: dict[str, Any] = {}

    if hasattr(params, "session_id"):
        params_dict["session_id"] = params.session_id

    if hasattr(params, "update"):
        params_dict["update"] = _extract_update(params.update)

    return (method, params_dict)


def _extract_agent_info(agent_info: Any) -> dict[str, Any]:
    """Extract agent info from SDK response."""
    if agent_info is None:
        return {}

    return {
        "name": getattr(agent_info, "name", "unknown"),
        "version": getattr(agent_info, "version", "unknown"),
    }


def _extract_capabilities(capabilities: Any) -> dict[str, Any]:
    """Extract capabilities from SDK response."""
    if capabilities is None:
        return {}

    result: dict[str, Any] = {}

    # Common capabilities
    if hasattr(capabilities, "load_session"):
        result["loadSession"] = capabilities.load_session
    if hasattr(capabilities, "supports_streaming"):
        result["supports_streaming"] = capabilities.supports_streaming
    if hasattr(capabilities, "tools"):
        result["tools"] = capabilities.tools or []
    if hasattr(capabilities, "prompts"):
        result["prompts"] = capabilities.prompts
    if hasattr(capabilities, "resources"):
        result["resources"] = capabilities.resources

    return result


def _extract_session_data(session: Any) -> dict[str, Any]:
    """Extract session data from SDK response."""
    if session is None:
        return {}

    result: dict[str, Any] = {}

    if hasattr(session, "id"):
        result["id"] = session.id
    if hasattr(session, "state"):
        result["state"] = session.state or {}
    if hasattr(session, "history"):
        result["history"] = session.history or []

    return result


def _extract_message_chunk(message: Any) -> dict[str, Any]:
    """Extract message chunk data."""
    if message is None:
        return {}

    result: dict[str, Any] = {}

    if hasattr(message, "role"):
        result["role"] = message.role
    if hasattr(message, "content"):
        result["content"] = _extract_content(message.content)

    return result


def _extract_content(content: Any) -> list[dict[str, Any]]:
    """Extract content blocks from message."""
    if content is None:
        return []

    result: list[dict[str, Any]] = []

    for block in content:
        block_dict: dict[str, Any] = {}
        if hasattr(block, "type"):
            block_dict["type"] = block.type
        if hasattr(block, "text"):
            block_dict["text"] = block.text
        if hasattr(block, "tool_use"):
            block_dict["tool_use"] = _extract_tool_use(block.tool_use)
        if hasattr(block, "tool_result"):
            block_dict["tool_result"] = _extract_tool_result(block.tool_result)
        result.append(block_dict)

    return result


def _extract_tool_use(tool_use: Any) -> dict[str, Any]:
    """Extract tool use data."""
    if tool_use is None:
        return {}

    return {
        "id": getattr(tool_use, "id", None),
        "name": getattr(tool_use, "name", None),
        "input": getattr(tool_use, "input", {}),
    }


def _extract_tool_result(tool_result: Any) -> dict[str, Any]:
    """Extract tool result data."""
    if tool_result is None:
        return {}

    return {
        "tool_use_id": getattr(tool_result, "tool_use_id", None),
        "content": getattr(tool_result, "content", None),
    }


def _extract_usage(usage: Any) -> dict[str, Any]:
    """Extract usage data."""
    if usage is None:
        return {}

    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


def _extract_update(update: Any) -> dict[str, Any]:
    """Extract update data from SDK notification."""
    if update is None:
        return {}

    result: dict[str, Any] = {}

    if hasattr(update, "session_update"):
        result["session_update"] = _extract_session_update(update.session_update)

    return result


def _extract_session_update(session_update: Any) -> dict[str, Any]:
    """Extract session update data."""
    if session_update is None:
        return {}

    result: dict[str, Any] = {}

    if hasattr(session_update, "thought"):
        result["thought"] = session_update.thought
    if hasattr(session_update, "message"):
        result["message"] = _extract_message_chunk(session_update.message)
    if hasattr(session_update, "tool_call"):
        result["tool_call"] = session_update.tool_call
    if hasattr(session_update, "tool_result"):
        result["tool_result"] = session_update.tool_result
    if hasattr(session_update, "usage"):
        result["usage"] = _extract_usage(session_update.usage)

    return result
