from uuid import uuid4
from utils.safe_paths import workspace_file
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models.image_prompt import ImagePrompt
from models.sql.image_asset import ImageAsset
from services.database import get_async_session
from services.image_generation_service import ImageGenerationService
from utils.asset_directory_utils import get_images_directory
from utils.asset_url_utils import to_public_asset_url
import os
import uuid
from utils.file_utils import get_file_name_with_random_uuid

IMAGES_ROUTER = APIRouter(prefix="/images", tags=["Images"])


def serialize_image_asset(image: ImageAsset) -> dict:
    return {
        "id": image.id,
        "created_at": image.created_at,
        "is_uploaded": image.is_uploaded,
        "path": to_public_asset_url(image.path),
        "extras": image.extras,
    }


@IMAGES_ROUTER.get("/generate")
async def generate_image(
    prompt: str, sql_session: AsyncSession = Depends(get_async_session)
):
    images_directory = get_images_directory()
    image_prompt = ImagePrompt(prompt=prompt)
    image_generation_service = ImageGenerationService(images_directory)

    image = await image_generation_service.generate_image(image_prompt)
    if not isinstance(image, ImageAsset):
        return image

    sql_session.add(image)
    await sql_session.commit()

    return to_public_asset_url(image.path)


@IMAGES_ROUTER.get("/generated", response_model=List[ImageAsset])
async def get_generated_images(sql_session: AsyncSession = Depends(get_async_session)):
    try:
        images = await sql_session.scalars(
            select(ImageAsset)
            .where(ImageAsset.is_uploaded == False)
            .order_by(ImageAsset.created_at.desc())
        )
        return [serialize_image_asset(image) for image in images]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve generated images: {str(e)}"
        )


@IMAGES_ROUTER.post("/upload")
async def upload_image(
    file: UploadFile = File(...), sql_session: AsyncSession = Depends(get_async_session)
):
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image exceeds 20 MiB")
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif content.startswith(b"\xff\xd8\xff"):
            extension = ".jpg"
        elif content.startswith((b"GIF87a", b"GIF89a")):
            extension = ".gif"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            extension = ".webp"
        else:
            raise HTTPException(status_code=400, detail="Upload a PNG, JPEG, GIF or WebP image")
        new_filename = str(uuid4()) + extension
        image_path = workspace_file(os.path.join(get_images_directory(), new_filename))
        with open(image_path, "wb") as f:
            f.write(content)

        image_asset = ImageAsset(path=image_path, is_uploaded=True)

        sql_session.add(image_asset)
        await sql_session.commit()

        return serialize_image_asset(image_asset)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to upload image")


@IMAGES_ROUTER.get("/uploaded", response_model=List[ImageAsset])
async def get_uploaded_images(sql_session: AsyncSession = Depends(get_async_session)):
    try:
        images = await sql_session.scalars(
            select(ImageAsset)
            .where(ImageAsset.is_uploaded == True)
            .order_by(ImageAsset.created_at.desc())
        )
        return [serialize_image_asset(image) for image in images]
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve uploaded images: {str(e)}"
        )


@IMAGES_ROUTER.delete("/{id}", status_code=204)
async def delete_uploaded_image_by_id(
    id: uuid.UUID, sql_session: AsyncSession = Depends(get_async_session)
):
    try:
        # Fetch the asset to get its actual file path
        image = await sql_session.get(ImageAsset, id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        os.remove(image.path)

        await sql_session.delete(image)
        await sql_session.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")
