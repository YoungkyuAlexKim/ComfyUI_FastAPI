import re
from fastapi import APIRouter, HTTPException, Request

from ..auth.user_management import _get_anon_id_from_request
from ..character_store import CharacterStore
from ..config import JOB_DB_PATH
from ..services.media_store import _locate_input_png_path, _locate_image_meta_path
from ..schemas.api_models import (
    CharactersResponse,
    CharacterUpsertRequest,
    CharacterUpsertResponse,
    OkResponse,
)


router = APIRouter(tags=["Characters"])
_store = CharacterStore(JOB_DB_PATH)

# Mention-friendly name rule: no spaces, keep it simple for non-dev users.
_NAME_RE = re.compile(r"^[A-Za-z0-9가-힣_-]{1,32}$")


def _normalize_name(name: str) -> str:
    try:
        s = str(name or "").strip()
    except Exception:
        s = ""
    return s


def _validate_ref_ids(owner_id: str, ids: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for x in ids or []:
        try:
            s = str(x or "").strip()
        except Exception:
            s = ""
        if not s or s in seen:
            continue
        seen.add(s)

        # 1) inputs store
        try:
            if _locate_input_png_path(owner_id, s):
                out.append(s)
                continue
        except Exception:
            pass

        # 2) generated gallery store
        try:
            meta = _locate_image_meta_path(owner_id, s)
            if meta:
                out.append(s)
                continue
        except Exception:
            pass

        raise HTTPException(status_code=400, detail=f"레퍼런스 이미지(id={s})를 찾지 못했습니다. 먼저 업로드/선택해 주세요.")
    return out


@router.get("/api/v1/characters", response_model=CharactersResponse)
async def list_characters(request: Request, include: str = "active"):
    owner_id = _get_anon_id_from_request(request)
    inc = str(include or "active").strip().lower()
    if inc not in ("active", "archived", "deleted", "all"):
        inc = "active"
    items = _store.list_characters(owner_id, status=inc)
    # Keep response small: only the data needed by UI/mentions
    return {"items": [
        {
            "character_id": it.get("character_id"),
            "name": it.get("name"),
            "reference_image_ids": it.get("reference_image_ids") or [],
            "thumbnail_image_id": it.get("thumbnail_image_id"),
            "status": it.get("status") or "active",
            "created_at": float(it.get("created_at") or 0.0),
            "updated_at": float(it.get("updated_at") or 0.0),
        }
        for it in items
    ]}


@router.post("/api/v1/characters", response_model=CharacterUpsertResponse)
async def upsert_character(req: CharacterUpsertRequest, request: Request):
    owner_id = _get_anon_id_from_request(request)
    name = _normalize_name(req.name)
    if not name or not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="캐릭터 이름은 1~32자, 공백 없이 (영문/숫자/한글/언더바/하이픈)만 사용할 수 있어요. 예: 제임스, Mariann_01",
        )

    ref_ids = _validate_ref_ids(owner_id, list(req.reference_image_ids or []))
    if len(ref_ids) != 6:
        raise HTTPException(status_code=400, detail="캐릭터 레퍼런스 이미지는 정확히 6장을 선택해 주세요.")

    # Use first reference as thumbnail by default
    thumb = ref_ids[0] if ref_ids else None
    try:
        ch = _store.upsert_character(owner_id, name=name, reference_image_ids=ref_ids, thumbnail_image_id=thumb)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="캐릭터를 저장하지 못했습니다. 입력 값을 확인해 주세요.") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="캐릭터를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.") from e

    return {
        "ok": True,
        "character": {
            "character_id": ch.get("character_id"),
            "name": ch.get("name"),
            "reference_image_ids": ch.get("reference_image_ids") or [],
            "thumbnail_image_id": ch.get("thumbnail_image_id"),
            "status": ch.get("status") or "active",
            "created_at": float(ch.get("created_at") or 0.0),
            "updated_at": float(ch.get("updated_at") or 0.0),
        },
    }


@router.post("/api/v1/characters/{name}/delete", response_model=OkResponse)
async def delete_character(name: str, request: Request):
    owner_id = _get_anon_id_from_request(request)
    nm = _normalize_name(name)
    if not nm:
        raise HTTPException(status_code=400, detail="Invalid name")
    ok = _store.soft_delete(owner_id, nm)
    if not ok:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"ok": True}

