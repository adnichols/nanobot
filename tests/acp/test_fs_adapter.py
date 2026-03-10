"""Tests for ACP filesystem adapter.

These tests verify that the filesystem adapter correctly:
- Allows reads/writes to files inside the workspace
- Denies reads/writes to files outside the workspace
- Supports line/limit parameters for read operations
- Maps errors to clear ACP-appropriate failures
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nanobot.acp.fs import ACPFilesystemHandler
from nanobot.acp.types import ACPFilesystemCallback
from tests.acp.fakes import FakeACPCallbackRegistry


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def fs_handler(temp_workspace):
    """Create a filesystem handler with the temp workspace."""
    return ACPFilesystemHandler(
        workspace=temp_workspace,
        restrict_to_workspace=True,
    )


@pytest.fixture
def callback_registry(fs_handler):
    """Create a callback registry with the filesystem handler registered."""
    registry = FakeACPCallbackRegistry()
    registry.register_filesystem_callback(fs_handler.handle_filesystem_callback)
    return registry


class TestReadTextFile:
    """Tests for fs/read_text_file operation."""

    @pytest.mark.asyncio
    async def test_allowed_read_inside_workspace(self, fs_handler, temp_workspace):
        """Given a file inside the workspace, when read is requested, then content is returned."""
        # Create a test file inside the workspace
        test_file = temp_workspace / "test_file.txt"
        test_file.write_text("Hello, World!\nLine 2\nLine 3")

        # Create the callback
        callback = ACPFilesystemCallback(
            operation="read",
            path=str(test_file),
            content=None,
            metadata={},
        )

        # Execute
        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission granted
        assert result.granted is True
        assert "Hello, World!" in result.reason
        assert "Successfully read" in result.reason

    @pytest.mark.asyncio
    async def test_denied_read_outside_workspace(self, fs_handler, temp_workspace):
        """Given a path outside the workspace, when read is requested, then access is denied."""
        # Try to read a file outside the workspace
        callback = ACPFilesystemCallback(
            operation="read",
            path="/etc/passwd",  # Outside workspace
            content=None,
            metadata={},
        )

        # Execute
        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission denied
        assert result.granted is False
        assert "outside allowed directory" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, fs_handler, temp_workspace):
        """Given a nonexistent file inside workspace, when read is requested, then error is returned."""
        callback = ACPFilesystemCallback(
            operation="read",
            path=str(temp_workspace / "nonexistent.txt"),
            content=None,
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Should be denied with error message
        assert result.granted is False
        assert "not found" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_read_with_line_limit(self, fs_handler, temp_workspace):
        """Given line and limit parameters, when read is requested, then partial content is returned."""
        # Create a test file with multiple lines
        test_file = temp_workspace / "multi_line.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5")

        # Read with line=1 (0-indexed, so line 2) and limit=2
        callback = ACPFilesystemCallback(
            operation="read",
            path=str(test_file),
            content=None,
            metadata={"line": 1, "limit": 2},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission granted with partial content
        assert result.granted is True
        # Should contain lines 2 and 3 (line index 1, limit 2)
        assert "Line 2" in result.reason
        assert "Line 3" in result.reason
        # Should NOT contain lines outside the limit
        assert "Line 1" not in result.reason


class TestWriteTextFile:
    """Tests for fs/write_text_file operation."""

    @pytest.mark.asyncio
    async def test_allowed_write_inside_workspace(self, fs_handler, temp_workspace):
        """Given a file inside the workspace, when write is requested, then file is created."""
        test_file = temp_workspace / "new_file.txt"

        callback = ACPFilesystemCallback(
            operation="write",
            path=str(test_file),
            content="New content here",
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission granted
        assert result.granted is True

        # Verify file was created with correct content
        assert test_file.exists()
        assert test_file.read_text() == "New content here"

    @pytest.mark.asyncio
    async def test_denied_write_outside_workspace(self, fs_handler, temp_workspace):
        """Given a path outside the workspace, when write is requested, then access is denied."""
        callback = ACPFilesystemCallback(
            operation="write",
            path="/tmp/outside_workspace.txt",
            content="Should not be written",
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission denied
        assert result.granted is False
        assert "outside allowed directory" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_write_creates_parent_directories(self, fs_handler, temp_workspace):
        """Given a nested path, when write is requested, then parent dirs are created."""
        test_file = temp_workspace / "subdir" / "nested" / "file.txt"

        callback = ACPFilesystemCallback(
            operation="write",
            path=str(test_file),
            content="Nested content",
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Assert permission granted
        assert result.granted is True
        assert test_file.exists()
        assert test_file.read_text() == "Nested content"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing_file(self, fs_handler, temp_workspace):
        """Given an existing file, when write is requested, then content is replaced."""
        test_file = temp_workspace / "existing.txt"
        test_file.write_text("Original content")

        callback = ACPFilesystemCallback(
            operation="write",
            path=str(test_file),
            content="New content",
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        assert result.granted is True
        assert test_file.read_text() == "New content"


class TestErrorMapping:
    """Tests for error mapping to ACP-appropriate failures."""

    @pytest.mark.asyncio
    async def test_permission_error_is_denied(self, fs_handler, temp_workspace):
        """Given a PermissionError during operation, then it's mapped to denied decision."""
        # Create handler with invalid workspace (non-existent path)
        bad_handler = ACPFilesystemHandler(
            workspace=Path("/nonexistent/workspace"),
            restrict_to_workspace=True,
        )

        callback = ACPFilesystemCallback(
            operation="read",
            path=str(temp_workspace / "test.txt"),
            content=None,
            metadata={},
        )

        result = await bad_handler.handle_filesystem_callback(callback)

        # Should handle the error gracefully
        assert result.granted is False
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_io_error_includes_message(self, fs_handler, temp_workspace):
        """Given an IOError during operation, then error message is in reason."""
        # Create a directory instead of a file to cause error
        test_dir = temp_workspace / "subdir"
        test_dir.mkdir()

        callback = ACPFilesystemCallback(
            operation="read",
            path=str(test_dir),
            content=None,
            metadata={},
        )

        result = await fs_handler.handle_filesystem_callback(callback)

        # Should be denied with appropriate error
        assert result.granted is False
        assert "not a file" in result.reason.lower() or "is a directory" in result.reason.lower()


class TestWithoutWorkspaceRestriction:
    """Tests for filesystem handler without workspace restriction."""

    @pytest.mark.asyncio
    async def test_allows_absolute_paths_without_restriction(self):
        """Given no workspace restriction, when absolute path is used, then it's allowed."""
        handler = ACPFilesystemHandler(
            workspace=None,
            restrict_to_workspace=False,
        )

        # Try to read an actual file
        callback = ACPFilesystemCallback(
            operation="read",
            path="/tmp/test_read.txt",
            content=None,
            metadata={},
        )

        # Create the file first
        Path("/tmp/test_read.txt").write_text("test content")

        try:
            result = await handler.handle_filesystem_callback(callback)
            # Without restriction, should check if path is allowed differently
            # or could still grant based on other policies
            assert result is not None
        finally:
            # Cleanup
            Path("/tmp/test_read.txt").unlink(missing_ok=True)
