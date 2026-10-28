"""Fixed local identity for the single-user application.

These dependency names are retained for router compatibility. They do not
validate tokens or create accounts; access is controlled by the deployment's
private network/reverse proxy boundary.
"""

from dataclasses import dataclass

from fastapi import WebSocket


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str = "local"
    email: str = ""
    display_name: str = "Local workspace"
    is_active: bool = True


LOCAL_USER = AuthenticatedUser()


async def get_current_user() -> AuthenticatedUser:
    return LOCAL_USER


async def get_optional_current_user() -> AuthenticatedUser:
    return LOCAL_USER


async def get_current_websocket_user(websocket: WebSocket) -> AuthenticatedUser:
    return LOCAL_USER
