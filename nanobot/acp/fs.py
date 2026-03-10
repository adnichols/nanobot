"""ACP Filesystem Client implementation.

This module provides filesystem operations for the ACP agent:
- fs/read_text_file: Read file content with workspace safety checks
- fs/write_text_file: Write file content with workspace safety checks

The implementation integrates with the callback registration hook from ACP-03
and reuses existing repo safety constraints for workspace boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Optional

from nanobot.acp.types import (
    ACPFilesystemCallback,
    ACPPermissionDecision,
)


def _resolve_path(
    path: str, workspace: Optional[Path] = None, allowed_dir: Optional[Path] = None
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction.

    This reuses the logic from nanobot/agent/tools/filesystem.py for consistency.

    Args:
        path: The file path to resolve
        workspace: Optional workspace directory for relative paths
        allowed_dir: Optional directory to restrict access to

    Returns:
        Resolved Path object

    Raises:
        PermissionError: If path is outside allowed directory
    """
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ACPFilesystemHandler:
    """Handler for ACP filesystem operations with workspace safety checks.

    This class implements the filesystem callback handler that:
    - Validates paths against workspace boundaries
    - Supports read operations with line/limit parameters
    - Supports write operations with parent directory creation
    - Maps errors to clear ACP-appropriate failures
    """

    # Maximum characters to read (from existing tool config)
    _MAX_CHARS = 128_000

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
        allowed_dir: Optional[Path] = None,
    ):
        """Initialize the filesystem handler.

        Args:
            workspace: Workspace directory for relative path resolution.
                     If restrict_to_workspace is True, this becomes the allowed directory.
            restrict_to_workspace: If True, restrict all operations to workspace directory.
            allowed_dir: Explicit allowed directory (overrides workspace if provided).
        """
        self._workspace = workspace
        self._restrict_to_workspace = restrict_to_workspace
        # Use allowed_dir if provided, otherwise use workspace as allowed_dir
        self._allowed_dir = (
            allowed_dir if allowed_dir else (workspace if restrict_to_workspace else None)
        )

    async def handle_filesystem_callback(
        self, callback: ACPFilesystemCallback
    ) -> ACPPermissionDecision:
        """Handle a filesystem permission request.

        This is the callback registered with the ACP runtime's
        register_filesystem_callback() hook.

        Args:
            callback: The filesystem callback containing operation details

        Returns:
            ACPPermissionDecision indicating whether the operation is allowed
        """
        operation = callback.operation
        path = callback.path

        try:
            if operation == "read":
                return await self._handle_read(callback)
            elif operation == "write":
                return await self._handle_write(callback)
            else:
                return ACPPermissionDecision(
                    request_id=callback.metadata.get("request_id", ""),
                    granted=False,
                    reason=f"Unsupported filesystem operation: {operation}",
                )
        except PermissionError as e:
            return ACPPermissionDecision(
                request_id=callback.metadata.get("request_id", ""),
                granted=False,
                reason=str(e),
            )
        except FileNotFoundError:
            return ACPPermissionDecision(
                request_id=callback.metadata.get("request_id", ""),
                granted=False,
                reason=f"File not found: {path}",
            )
        except IsADirectoryError:
            return ACPPermissionDecision(
                request_id=callback.metadata.get("request_id", ""),
                granted=False,
                reason=f"Cannot read directory: {path} is a directory, not a file",
            )
        except Exception as e:
            return ACPPermissionDecision(
                request_id=callback.metadata.get("request_id", ""),
                granted=False,
                reason=f"Error: {str(e)}",
            )

    async def _handle_read(self, callback: ACPFilesystemCallback) -> ACPPermissionDecision:
        """Handle a read text file operation.

        Args:
            callback: The filesystem callback with read operation details

        Returns:
            ACPPermissionDecision with content if granted
        """
        path = callback.path
        metadata = callback.metadata

        # Resolve the path with workspace safety checks
        file_path = _resolve_path(path, self._workspace, self._allowed_dir)

        # Check if file exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # Check if it's a file (not a directory)
        if not file_path.is_file():
            raise IsADirectoryError(f"{path} is a directory, not a file")

        # Check file size
        size = file_path.stat().st_size
        if size > self._MAX_CHARS * 4:
            return ACPPermissionDecision(
                request_id=metadata.get("request_id", ""),
                granted=False,
                reason=(
                    f"File too large ({size:,} bytes). "
                    "Use exec tool with head/tail/grep to read portions."
                ),
            )

        # Read the content
        content = file_path.read_text(encoding="utf-8")

        # Apply line/limit parameters if provided
        line = metadata.get("line")
        limit = metadata.get("limit")

        if line is not None or limit is not None:
            lines = content.splitlines()
            start_line = line if line is not None else 0
            limit_count = limit if limit is not None else len(lines)
            selected_lines = lines[start_line : start_line + limit_count]
            content = "\n".join(selected_lines)

        # Truncate if still too large
        if len(content) > self._MAX_CHARS:
            content = (
                content[: self._MAX_CHARS] + f"\n\n... (truncated, {len(content):,} chars total)"
            )

        return ACPPermissionDecision(
            request_id=metadata.get("request_id", ""),
            granted=True,
            reason=f"Successfully read {len(content)} characters from {path}:\n\n{content}",
        )

    async def _handle_write(self, callback: ACPFilesystemCallback) -> ACPPermissionDecision:
        """Handle a write text file operation.

        Args:
            callback: The filesystem callback with write operation details

        Returns:
            ACPPermissionDecision indicating success
        """
        path = callback.path
        content = callback.content
        metadata = callback.metadata

        if content is None:
            return ACPPermissionDecision(
                request_id=metadata.get("request_id", ""),
                granted=False,
                reason="Write operation requires content parameter",
            )

        # Resolve the path with workspace safety checks
        file_path = _resolve_path(path, self._workspace, self._allowed_dir)

        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the content
        file_path.write_text(content, encoding="utf-8")

        return ACPPermissionDecision(
            request_id=metadata.get("request_id", ""),
            granted=True,
            reason=f"Successfully wrote {len(content)} bytes to {path}",
        )


# Type alias for the callback handler
FilesystemCallbackHandler = Callable[[ACPFilesystemCallback], Awaitable[ACPPermissionDecision]]


def create_filesystem_handler(
    workspace: Optional[Path] = None,
    restrict_to_workspace: bool = True,
) -> ACPFilesystemHandler:
    """Create a configured filesystem handler.

    This is a convenience factory function for creating a handler
    with common configurations.

    Args:
        workspace: Workspace directory for path resolution
        restrict_to_workspace: Whether to restrict to workspace directory

    Returns:
        Configured ACPFilesystemHandler instance
    """
    return ACPFilesystemHandler(
        workspace=workspace,
        restrict_to_workspace=restrict_to_workspace,
    )
