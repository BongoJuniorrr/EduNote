import os


def get_internal_next_base_url() -> str:
    base_path = (os.getenv("NEXT_PUBLIC_BASE_PATH") or "").rstrip("/")
    if not base_path or base_path == "/":
        return "http://localhost"
    return f"http://localhost{base_path}"


def build_internal_next_url(path: str) -> str:
    normalized_path = f"/{path.lstrip('/')}"
    return f"{get_internal_next_base_url()}{normalized_path}"
