"""Local workspace identity and filesystem safety helpers."""

from .auth import (
    LOCAL_USER,
    AuthenticatedUser,
    get_current_user,
    get_current_websocket_user,
    get_optional_current_user,
)

__all__ = [
    "LOCAL_USER",
    "AuthenticatedUser",
    "get_current_user",
    "get_current_websocket_user",
    "get_optional_current_user",
]
