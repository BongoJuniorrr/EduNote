import aiohttp
from fastapi import HTTPException
from models.presentation_layout import PresentationLayoutModel
from utils.internal_next_url import build_internal_next_url

async def get_layout_by_name(layout_name: str) -> PresentationLayoutModel:
    url = build_internal_next_url(f"/api/template?group={layout_name}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise HTTPException(
                    status_code=404,
                    detail=f"Template '{layout_name}' not found: {error_text}"
                )
            layout_json = await response.json()
    # Parse the JSON into your Pydantic model
    return PresentationLayoutModel(**layout_json)
