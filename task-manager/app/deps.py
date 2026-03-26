"""Shared dependencies for workspace-aware routes."""

from fastapi import Header, HTTPException


def get_workspace_id(x_workspace_id: int | None = Header(default=None)) -> int | None:
    """Extract workspace ID from request header."""
    return x_workspace_id
