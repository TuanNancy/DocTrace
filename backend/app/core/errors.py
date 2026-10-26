"""Structured API errors shared by workspace-aware routers.

Errors that clients must branch on carry a stable ``code``. Plain string
details remain valid for legacy endpoints; the frontend accepts both shapes.
"""
from __future__ import annotations

from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, **extra) -> HTTPException:
    """Build an HTTPException whose detail is ``{code, message, ...}``."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
    )
