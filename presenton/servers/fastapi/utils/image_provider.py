from enums.image_provider import ImageProvider
from utils.get_env import (
    get_disable_image_generation_env,
    get_image_provider_env,
)
from utils.parsers import parse_bool_or_none


def is_image_generation_disabled() -> bool:
    return parse_bool_or_none(get_disable_image_generation_env()) or False


def is_pixels_selected() -> bool:
    return ImageProvider.PEXELS == get_selected_image_provider()


def is_pixabay_selected() -> bool:
    return ImageProvider.PIXABAY == get_selected_image_provider()


def is_gemini_flash_selected() -> bool:
    return ImageProvider.GEMINI_FLASH == get_selected_image_provider()


def is_nanobanana_pro_selected() -> bool:
    return ImageProvider.NANOBANANA_PRO == get_selected_image_provider()


def is_dalle3_selected() -> bool:
    return ImageProvider.DALLE3 == get_selected_image_provider()


def is_gpt_image_1_5_selected() -> bool:
    return ImageProvider.GPT_IMAGE_1_5 == get_selected_image_provider()


def is_comfyui_selected() -> bool:
    return ImageProvider.COMFYUI == get_selected_image_provider()


def get_selected_image_provider() -> ImageProvider | None:
    """
    Get the selected image provider from environment variables.
    Returns:
        ImageProvider: The selected image provider.
    """
    image_provider_env = get_image_provider_env()
    if image_provider_env:
        normalized = image_provider_env.strip().lower()
        # Accept direct model names for Gemini image generation and map them
        # to the corresponding internal provider enum.
        model_alias_map = {
            "gemini-2.5-flash-image-preview": ImageProvider.GEMINI_FLASH,
            "models/gemini-2.5-flash-image-preview": ImageProvider.GEMINI_FLASH,
            "gemini-3-pro-image-preview": ImageProvider.NANOBANANA_PRO,
            "models/gemini-3-pro-image-preview": ImageProvider.NANOBANANA_PRO,
            "nano-banana-pro-preview": ImageProvider.NANOBANANA_PRO,
            "models/nano-banana-pro-preview": ImageProvider.NANOBANANA_PRO,
        }

        mapped_provider = model_alias_map.get(normalized)
        if mapped_provider:
            return mapped_provider

        return ImageProvider(normalized)
    return None
