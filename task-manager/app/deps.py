"""Shared dependencies for workspace-aware routes."""

from fastapi import Header, HTTPException


def get_workspace_id(x_workspace_id: int | None = Header(default=None)) -> int | None:
    """Extract workspace ID from request header."""
    return x_workspace_id


def get_user_id(x_user_id: int | None = Header(default=None)) -> int | None:
    """Extract the acting user's ID from the ``X-User-Id`` header.

    Used to attribute TaskHistory entries to the user who performed the
    action (create, move, edit, delete). Returns None if the header is
    missing so legacy clients keep working — older history rows then
    simply have NULL ``changed_by_id``.
    """
    return x_user_id
