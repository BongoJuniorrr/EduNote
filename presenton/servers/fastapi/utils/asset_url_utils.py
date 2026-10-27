import os

from utils.get_env import get_app_data_directory_env


DEFAULT_PROXY_BASE_PATH = "/slide_pro/_presenton"


def get_proxy_base_path() -> str:
    return (os.getenv("PRESENTON_BASE_PATH") or DEFAULT_PROXY_BASE_PATH).rstrip("/")


def to_public_asset_url(path: str | None) -> str | None:
    if not path:
        return path

    normalized = path.replace("\\", "/")

    if normalized.startswith(("http://", "https://", "data:")):
        return normalized

    proxy_base = get_proxy_base_path()
    if normalized == proxy_base or normalized.startswith(f"{proxy_base}/"):
        return normalized

    if normalized.startswith(("app_data/", "static/")):
        normalized = f"/{normalized}"

    if normalized.startswith("/app_data/") or normalized.startswith("/static/"):
        return f"{proxy_base}{normalized}"

    app_data_dir = (get_app_data_directory_env() or "").rstrip("/\\").replace("\\", "/")
    if app_data_dir and normalized.startswith(f"{app_data_dir}/"):
        relative_path = normalized[len(app_data_dir) + 1 :]
        return f"{proxy_base}/app_data/{relative_path}"

    return normalized


def resolve_local_asset_path(path: str | None) -> str | None:
    if not path:
        return path

    normalized = path.replace("\\", "/")
    proxy_base = get_proxy_base_path()

    if normalized == proxy_base:
        normalized = "/"
    elif normalized.startswith(f"{proxy_base}/"):
        normalized = normalized[len(proxy_base) :]

    if normalized.startswith(("app_data/", "static/")):
        normalized = f"/{normalized}"

    if normalized.startswith("/app_data/images/"):
        app_data_dir = (get_app_data_directory_env() or "").rstrip("/\\")
        relative_path = normalized[len("/app_data/images/") :]
        return os.path.join(app_data_dir, "images", relative_path)

    if normalized.startswith("/static/"):
        relative_path = normalized[len("/static/") :]
        return os.path.join("static", relative_path)

    if os.path.isabs(normalized):
        return normalized

    app_data_dir = (get_app_data_directory_env() or "").rstrip("/\\")
    return os.path.join(app_data_dir, "images", normalized)
