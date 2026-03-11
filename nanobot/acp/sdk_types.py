"""Type conversions between nanobot domain types and ACP wire payloads."""

from __future__ import annotations

from typing import Any, Optional

from nanobot.acp.types import ACPInitializeRequest


def to_sdk_initialize_params(
    request: ACPInitializeRequest,
) -> dict[str, Any]:
    """Convert nanobot's ACPInitializeRequest to ACP initialize params.

    Args:
        request: Nanobot's initialize request.

    Returns:
        ACP wire payload ready for sending.
    """
    del request
    return {
        "protocolVersion": 1,
        "clientCapabilities": {},
        "clientInfo": {
            "name": "nanobot",
            "version": "0.1.0",
        },
    }


def to_sdk_new_session_params(
    cwd: str,
) -> dict[str, Any]:
    """Convert cwd to ACP session/new params.

    Args:
        cwd: Working directory for the ACP session.

    Returns:
        ACP wire payload ready for sending.
    """
    return {
        "cwd": cwd,
        "mcpServers": [],
    }


def to_sdk_prompt_params(
    content: str,
    session_id: str,
) -> dict[str, Any]:
    """Convert nanobot's prompt request to ACP session/prompt params.

    Args:
        content: The prompt content.
        session_id: The session ID to send the prompt to.

    Returns:
        ACP wire payload ready for sending.
    """
    return {
        "sessionId": session_id,
        "prompt": [
            {
                "type": "text",
                "text": content,
            }
        ],
    }


def to_sdk_load_session_params(
    session_id: str,
    cwd: str,
) -> dict[str, Any]:
    """Convert session ID to ACP session/load params.

    Args:
        session_id: The session ID to load.
        cwd: Working directory for the ACP session.

    Returns:
        ACP wire payload ready for sending.
    """
    return {
        "sessionId": session_id,
        "cwd": cwd,
        "mcpServers": [],
    }


def to_sdk_cancel_params(
    session_id: str,
    request_id: Optional[str | int] = None,
) -> dict[str, Any]:
    """Convert nanobot's cancel request to ACP session/cancel params.

    Args:
        session_id: The session ID to cancel.
        request_id: Optional request ID to cancel specific operation.

    Returns:
        ACP wire payload ready for sending.
    """
    params: dict[str, Any] = {"sessionId": session_id}
    if request_id is not None:
        params["requestId"] = request_id
    return params


def from_sdk_initialize_response(response: Any) -> dict[str, Any]:
    """Convert SDK initialize response to nanobot dict format.

    Args:
        response: SDK InitializeResponse.

    Returns:
        Dict with agent info and capabilities.
    """
    result: dict[str, Any] = {}

    data = _as_dict(response)

    protocol_version = _first(data, "protocol_version", "protocolVersion")
    if protocol_version is not None:
        result["protocol_version"] = protocol_version

    agent_info = _first(data, "agent_info", "agentInfo")
    if agent_info is not None:
        result["agent_info"] = _extract_agent_info(agent_info)

    capabilities = _first(data, "capabilities", "agentCapabilities")
    if capabilities is not None:
        result["capabilities"] = _extract_capabilities(capabilities)

    return result


def from_sdk_session_response(response: Any) -> dict[str, Any]:
    """Convert SDK session response to nanobot dict format.

    Args:
        response: SDK session response (NewSessionResponse or LoadSessionResponse).

    Returns:
        Dict with session_id and optional session data.
    """
    result: dict[str, Any] = {}

    data = _as_dict(response)

    session_id = _first(data, "session_id", "sessionId", "sessionID")
    if session_id is not None:
        result["session_id"] = session_id

    session = _first(data, "session")
    if session is not None:
        result["session"] = _extract_session_data(session)

    return result


def from_sdk_prompt_chunk(chunk: Any) -> dict[str, Any]:
    """Convert SDK prompt response chunk to nanobot stream chunk format.

    Args:
        chunk: SDK response chunk.

    Returns:
        Dict with chunk data for nanobot's stream handling.
    """
    result: dict[str, Any] = {}

    data = _as_dict(chunk)

    session_id = _first(data, "session_id", "sessionId")
    if session_id is not None:
        result["session_id"] = session_id

    message = _first(data, "message")
    if message is not None:
        result["message"] = _extract_message_chunk(message)
        content = _message_text(result["message"])
        if content:
            result["content"] = content

    content = _first(data, "content")
    if isinstance(content, str) and content:
        result["content"] = content

    usage = _first(data, "usage")
    if usage is not None:
        result["usage"] = _extract_usage(usage)

    stop_reason = _first(data, "stop_reason", "stopReason")
    if stop_reason is not None:
        result["stop_reason"] = stop_reason

    return result


def from_sdk_notification(
    notification: Any, params: Any | None = None
) -> tuple[str, dict[str, Any]]:
    """Convert SDK notification to method and params for routing.

    Args:
        notification: SDK notification.

    Returns:
        Tuple of (method, params dict) for routing to appropriate handler.
    """
    if params is None:
        data = _as_dict(notification)
        method = str(_first(data, "method") or "unknown")
        raw_params = _first(data, "params") or {}
    else:
        method = str(notification)
        raw_params = params

    params_dict = _as_dict(raw_params)
    session_id = _first(params_dict, "session_id", "sessionId")
    if session_id is not None:
        params_dict["session_id"] = session_id

    update = _first(params_dict, "update")
    if update is not None:
        params_dict["update"] = _extract_update(update)

    return (method, params_dict)


def _extract_agent_info(agent_info: Any) -> dict[str, Any]:
    """Extract agent info from SDK response."""
    if agent_info is None:
        return {}

    data = _as_dict(agent_info)
    return {
        "name": _first(data, "name") or "unknown",
        "version": _first(data, "version") or "unknown",
    }


def _extract_capabilities(capabilities: Any) -> dict[str, Any]:
    """Extract capabilities from SDK response."""
    if capabilities is None:
        return {}

    result: dict[str, Any] = {}

    data = _as_dict(capabilities)

    load_session = _first(data, "load_session", "loadSession")
    if load_session is not None:
        result["loadSession"] = load_session

    supports_streaming = _first(data, "supports_streaming", "supportsStreaming")
    if supports_streaming is not None:
        result["supports_streaming"] = supports_streaming

    tools = _first(data, "tools")
    if tools is not None:
        result["tools"] = tools

    prompts = _first(data, "prompts", "promptCapabilities")
    if prompts is not None:
        result["prompts"] = prompts

    resources = _first(data, "resources", "mcpCapabilities")
    if resources is not None:
        result["resources"] = resources

    session_capabilities = _first(data, "sessionCapabilities")
    if session_capabilities is not None:
        result["sessionCapabilities"] = session_capabilities

    return result


def _extract_session_data(session: Any) -> dict[str, Any]:
    """Extract session data from SDK response."""
    if session is None:
        return {}

    result: dict[str, Any] = {}

    data = _as_dict(session)

    session_id = _first(data, "id", "sessionId")
    if session_id is not None:
        result["id"] = session_id

    state = _first(data, "state")
    if state is not None:
        result["state"] = state

    history = _first(data, "history", "messages")
    if history is not None:
        result["history"] = history

    return result


def _extract_message_chunk(message: Any) -> dict[str, Any]:
    """Extract message chunk data."""
    if message is None:
        return {}

    result: dict[str, Any] = {}

    data = _as_dict(message)

    role = _first(data, "role")
    if role is not None:
        result["role"] = role

    content = _first(data, "content")
    if content is not None:
        result["content"] = _extract_content(content)

    return result


def _extract_content(content: Any) -> list[dict[str, Any]]:
    """Extract content blocks from message."""
    if content is None:
        return []

    result: list[dict[str, Any]] = []

    for block in content:
        block_data = _as_dict(block)
        block_dict: dict[str, Any] = {}
        block_type = _first(block_data, "type")
        if block_type is not None:
            block_dict["type"] = block_type
        text = _first(block_data, "text")
        if text is not None:
            block_dict["text"] = text
        tool_use = _first(block_data, "tool_use", "toolUse")
        if tool_use is not None:
            block_dict["tool_use"] = _extract_tool_use(tool_use)
        tool_result = _first(block_data, "tool_result", "toolResult")
        if tool_result is not None:
            block_dict["tool_result"] = _extract_tool_result(tool_result)
        result.append(block_dict)

    return result


def _extract_tool_use(tool_use: Any) -> dict[str, Any]:
    """Extract tool use data."""
    if tool_use is None:
        return {}

    data = _as_dict(tool_use)
    return {
        "id": _first(data, "id"),
        "name": _first(data, "name"),
        "input": _first(data, "input") or {},
    }


def _extract_tool_result(tool_result: Any) -> dict[str, Any]:
    """Extract tool result data."""
    if tool_result is None:
        return {}

    data = _as_dict(tool_result)
    return {
        "tool_use_id": _first(data, "tool_use_id", "toolUseId"),
        "content": _first(data, "content"),
    }


def _extract_usage(usage: Any) -> dict[str, Any]:
    """Extract usage data."""
    if usage is None:
        return {}

    data = _as_dict(usage)
    return {
        "input_tokens": _first(data, "input_tokens", "inputTokens") or 0,
        "output_tokens": _first(data, "output_tokens", "outputTokens") or 0,
        "total_tokens": _first(data, "total_tokens", "totalTokens") or 0,
    }


def _extract_update(update: Any) -> dict[str, Any]:
    """Extract update data from SDK notification."""
    if update is None:
        return {}

    result: dict[str, Any] = {}

    data = _as_dict(update)

    session_update = _first(data, "session_update", "sessionUpdate")
    if session_update is not None:
        result["session_update"] = _extract_session_update(session_update)

    for key in (
        "availableCommands",
        "used",
        "size",
        "cost",
        "content",
        "message",
        "toolCall",
        "toolResult",
        "thought",
        "usage",
    ):
        value = _first(data, key)
        if value is not None:
            result[key] = value

    return result


def _extract_session_update(session_update: Any) -> dict[str, Any]:
    """Extract session update data."""
    if session_update is None:
        return {}

    result: dict[str, Any] = {}

    if isinstance(session_update, str):
        result["kind"] = session_update
        return result

    data = _as_dict(session_update)

    thought = _first(data, "thought")
    if thought is not None:
        result["thought"] = thought

    message = _first(data, "message")
    if message is not None:
        result["message"] = _extract_message_chunk(message)

    tool_call = _first(data, "tool_call", "toolCall")
    if tool_call is not None:
        result["tool_call"] = tool_call

    tool_result = _first(data, "tool_result", "toolResult")
    if tool_result is not None:
        result["tool_result"] = tool_result

    usage = _first(data, "usage")
    if usage is not None:
        result["usage"] = _extract_usage(usage)

    return result


def _as_dict(value: Any) -> dict[str, Any]:
    """Normalize Pydantic models and objects to dicts when possible."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return {}


def _first(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present key from a normalized dict."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def _message_text(message: dict[str, Any]) -> str:
    """Extract plain text from a normalized message payload."""
    parts: list[str] = []
    for block in message.get("content", []):
        text = block.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "".join(parts)
