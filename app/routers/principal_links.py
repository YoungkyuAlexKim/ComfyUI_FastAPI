from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from ..auth.mcp_identity import (
    mcp_client_ip_allowed,
    parse_allowed_mcp_networks,
    principal_for_mcp_ip,
)
from ..auth.user_management import _get_anon_id_from_request
from ..principal_link_store import PrincipalLinkConflict, PrincipalLinkStore
from ..services.generation_commands import resolve_client_ip
from ..services.principal_links import mcp_web_link_enabled


router = APIRouter(prefix="/api/v1/principal-links", tags=["Principal Links"])


def _resolved_mcp_identity(request: Request) -> tuple[str, str]:
    peer_ip = getattr(getattr(request, "client", None), "host", None)
    client_ip, _ = resolve_client_ip(
        peer_ip,
        request.headers.get("x-forwarded-for"),
        os.getenv("TRUSTED_PROXY_CIDRS"),
    )
    try:
        parse_allowed_mcp_networks(os.getenv("MCP_ALLOWED_CLIENT_CIDRS"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="mcp_client_cidr_policy_invalid") from exc
    if not mcp_client_ip_allowed(client_ip, os.getenv("MCP_ALLOWED_CLIENT_CIDRS")):
        raise HTTPException(status_code=403, detail="mcp_client_ip_not_allowed")
    return principal_for_mcp_ip(client_ip), client_ip


def _store(request: Request) -> PrincipalLinkStore:
    store = getattr(request.app.state, "principal_link_store", None)
    if not isinstance(store, PrincipalLinkStore):
        raise HTTPException(status_code=503, detail="principal_link_store_unavailable")
    return store


@router.get("/mcp")
async def mcp_link_status(request: Request):
    if not mcp_web_link_enabled():
        return {"enabled": False, "state": "disabled", "connected": False}
    web_id = _get_anon_id_from_request(request)
    mcp_id, _ = _resolved_mcp_identity(request)
    store = _store(request)
    linked_web_id = store.web_principal_for_mcp(mcp_id)
    linked_mcp_ids = store.mcp_principals_for_web(web_id)
    asset_service = getattr(request.app.state, "asset_service", None)
    candidate_image_count = 0
    linked_image_count = 0
    if asset_service is not None:
        candidate_image_count = asset_service.count_media(mcp_id, "image")
        if linked_mcp_ids:
            linked_image_count = asset_service.count_media_for_owners(linked_mcp_ids, "image")

    if linked_web_id == web_id:
        state = "connected"
    elif linked_web_id:
        state = "conflict"
    elif candidate_image_count > 0:
        state = "available"
    else:
        state = "empty"
    return {
        "enabled": True,
        "state": state,
        "connected": state == "connected",
        "can_link": state in {"available", "empty"},
        "candidate_image_count": candidate_image_count if state != "conflict" else 0,
        "linked_workspace_count": len(linked_mcp_ids),
        "linked_image_count": linked_image_count,
    }


@router.post("/mcp")
async def link_current_mcp_workspace(request: Request):
    if not mcp_web_link_enabled():
        raise HTTPException(status_code=404, detail="mcp_web_link_disabled")
    web_id = _get_anon_id_from_request(request)
    mcp_id, client_ip = _resolved_mcp_identity(request)
    try:
        _store(request).link(web_id, mcp_id, client_ip=client_ip)
    except PrincipalLinkConflict as exc:
        raise HTTPException(status_code=409, detail="mcp_workspace_already_linked") from exc
    return {"ok": True, "connected": True}


@router.delete("/mcp")
async def unlink_current_mcp_workspace(request: Request):
    if not mcp_web_link_enabled():
        raise HTTPException(status_code=404, detail="mcp_web_link_disabled")
    web_id = _get_anon_id_from_request(request)
    mcp_id, client_ip = _resolved_mcp_identity(request)
    if not _store(request).unlink(web_id, mcp_id, client_ip=client_ip):
        raise HTTPException(status_code=404, detail="mcp_workspace_link_not_found")
    return {"ok": True, "connected": False}
