from fastapi import APIRouter

from ..schemas.api_models import GlobalCharactersResponse
from ..services.global_character_store import list_global_characters


router = APIRouter(tags=["Characters"])


@router.get("/api/v1/global-characters", response_model=GlobalCharactersResponse)
async def list_global_characters_endpoint(include: str = "valid"):
    """
    Global characters are loaded from filesystem (outputs/global/characters/<name>/...).
    - include=valid (default): only characters with >= required reference images
    - include=all: also include invalid folders (useful for debugging)
    """
    inc = str(include or "valid").strip().lower()
    include_invalid = inc in ("all", "invalid", "debug")
    items = list_global_characters(include_invalid=include_invalid)
    return {
        "items": [
            {
                "name": str(it.get("name") or ""),
                "reference_image_count": int(it.get("reference_image_count") or 0),
                "thumbnail_url": it.get("thumbnail_url"),
            }
            for it in items
            if it.get("name")
        ]
    }

