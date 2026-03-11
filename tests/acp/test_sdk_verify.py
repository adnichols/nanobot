"""Verify SDK API surface and version for ACP migration.

These tests verify that the agent-client-protocol SDK is importable
and provides the expected API surface for ACP integration.
"""

import importlib.metadata


def test_sdk_version_pinned():
    """Verify exact SDK version is installed."""
    version = importlib.metadata.version("agent-client-protocol")
    assert version == "0.8.1"


def test_sdk_connection_importable():
    """Verify Connection class is importable."""
    from acp.connection import Connection

    assert Connection is not None


def test_sdk_schema_importable():
    """Verify schema types are importable."""
    from acp import schema

    assert schema.InitializeRequest is not None
    assert schema.NewSessionRequest is not None
    assert schema.PromptRequest is not None
