"""
Settings API Router (Simplified)
================================

Manages basic UI settings: theme, language, sidebar customization.
Configuration for LLM/Embedding/TTS/Search is handled by the unified config service.
"""

import json
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.security.auth import AuthenticatedUser, get_current_user

router = APIRouter()

# Settings file path for UI preferences (stored in settings folder with other configs)
SETTINGS_FILE = (
    Path(__file__).parent.parent.parent.parent / "data" / "user" / "settings" / "interface.json"
)

# Default sidebar navigation order
DEFAULT_SIDEBAR_NAV_ORDER = {
    "start": ["/", "/history", "/knowledge", "/notebook", "/about"],
    "learnResearch": [
        "/question",
        "/solver",
        "/guide",
        "/mission",
        "/ideagen",
        "/slide_pro",
        "/edu_studio",
        "/research",
        "/co_writer",
    ],
}

# Default UI settings
LEGACY_SIDEBAR_DESCRIPTION = "✨ Information Technology Project @ VGU"
NEW_SIDEBAR_DESCRIPTION = "✨ Learn with AI! @ BongoJuniorrr"

DEFAULT_UI_SETTINGS = {
    "theme": "light",
    "language": "en",
    "sidebar_description": NEW_SIDEBAR_DESCRIPTION,
    "sidebar_nav_order": DEFAULT_SIDEBAR_NAV_ORDER,
}


def _merge_sidebar_nav_order(order: dict | None) -> dict:
    """
    Merge persisted sidebar order with current defaults.

    This keeps user-customized order while auto-appending newly introduced routes.
    """
    if not isinstance(order, dict):
        return DEFAULT_SIDEBAR_NAV_ORDER.copy()

    merged = {}
    for group_name, default_items in DEFAULT_SIDEBAR_NAV_ORDER.items():
        group_items = order.get(group_name, [])
        if not isinstance(group_items, list):
            group_items = []

        # Keep valid user items that still exist in defaults.
        normalized = [item for item in group_items if item in default_items]

        # Append any newly added default routes.
        for item in default_items:
            if item not in normalized:
                normalized.append(item)

        merged[group_name] = normalized

    return merged


class SidebarNavOrder(BaseModel):
    start: List[str]
    learnResearch: List[str]


class UISettings(BaseModel):
    theme: Literal["light", "dark"] = "light"
    language: Literal["zh", "en"] = "en"
    sidebar_description: Optional[str] = None
    sidebar_nav_order: Optional[SidebarNavOrder] = None


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark"]


class LanguageUpdate(BaseModel):
    language: Literal["zh", "en"]


class SidebarDescriptionUpdate(BaseModel):
    description: str


class SidebarNavOrderUpdate(BaseModel):
    nav_order: SidebarNavOrder


def load_ui_settings(user_id: str | None = None) -> dict:
    """Load UI-specific settings from json file"""
    settings_file = SETTINGS_FILE
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as f:
                saved = json.load(f)
                merged = {**DEFAULT_UI_SETTINGS, **saved}
                if merged.get("sidebar_description") == LEGACY_SIDEBAR_DESCRIPTION:
                    merged["sidebar_description"] = NEW_SIDEBAR_DESCRIPTION
                merged["sidebar_nav_order"] = _merge_sidebar_nav_order(
                    merged.get("sidebar_nav_order")
                )
                return merged
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def save_ui_settings(settings: dict, user_id: str | None = None):
    """Save UI settings"""
    settings_file = SETTINGS_FILE
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


@router.get("")
async def get_settings(user: AuthenticatedUser = Depends(get_current_user)):
    """Get UI settings."""
    return {"ui": load_ui_settings(user.id)}


@router.put("/theme")
async def update_theme(update: ThemeUpdate, user: AuthenticatedUser = Depends(get_current_user)):
    """Update UI theme"""
    current_ui = load_ui_settings(user.id)
    current_ui["theme"] = update.theme
    save_ui_settings(current_ui, user.id)
    return {"theme": update.theme}


@router.put("/language")
async def update_language(
    update: LanguageUpdate, user: AuthenticatedUser = Depends(get_current_user)
):
    """Update UI language"""
    current_ui = load_ui_settings(user.id)
    current_ui["language"] = update.language
    save_ui_settings(current_ui, user.id)
    return {"language": update.language}


@router.put("/ui")
async def update_ui_settings(
    update: UISettings, user: AuthenticatedUser = Depends(get_current_user)
):
    """Update all UI settings"""
    current_ui = load_ui_settings(user.id)
    update_dict = update.model_dump(exclude_none=True)
    if "sidebar_nav_order" in update_dict:
        update_dict["sidebar_nav_order"] = _merge_sidebar_nav_order(
            update_dict["sidebar_nav_order"]
        )
    current_ui.update(update_dict)
    save_ui_settings(current_ui, user.id)
    return current_ui


@router.post("/reset")
async def reset_settings(user: AuthenticatedUser = Depends(get_current_user)):
    """Reset UI settings to default"""
    save_ui_settings(DEFAULT_UI_SETTINGS, user.id)
    return DEFAULT_UI_SETTINGS


@router.get("/themes")
async def get_themes():
    """Get available theme list"""
    return {
        "themes": [
            {"id": "light", "name": "Light"},
            {"id": "dark", "name": "Dark"},
        ]
    }


@router.get("/sidebar")
async def get_sidebar_settings(user: AuthenticatedUser = Depends(get_current_user)):
    """Get sidebar customization settings"""
    current_ui = load_ui_settings(user.id)
    return {
        "description": current_ui.get(
            "sidebar_description", DEFAULT_UI_SETTINGS["sidebar_description"]
        ),
        "nav_order": current_ui.get("sidebar_nav_order", DEFAULT_UI_SETTINGS["sidebar_nav_order"]),
    }


@router.put("/sidebar/description")
async def update_sidebar_description(
    update: SidebarDescriptionUpdate, user: AuthenticatedUser = Depends(get_current_user)
):
    """Update sidebar description"""
    current_ui = load_ui_settings(user.id)
    current_ui["sidebar_description"] = update.description
    save_ui_settings(current_ui, user.id)
    return {"description": update.description}


@router.put("/sidebar/nav-order")
async def update_sidebar_nav_order(
    update: SidebarNavOrderUpdate, user: AuthenticatedUser = Depends(get_current_user)
):
    """Update sidebar navigation order"""
    current_ui = load_ui_settings(user.id)
    current_ui["sidebar_nav_order"] = _merge_sidebar_nav_order(update.nav_order.model_dump())
    save_ui_settings(current_ui, user.id)
    return {"nav_order": current_ui["sidebar_nav_order"]}
