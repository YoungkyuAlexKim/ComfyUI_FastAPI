"""Read-side helpers for explicit browser/MCP workspace links."""

from __future__ import annotations

import os
from typing import Any

from ..auth.user_management import _parse_bool, require_principal_id


def mcp_web_link_enabled() -> bool:
    return _parse_bool(os.getenv("MCP_WEB_LINK_ENABLED"), True)


def linked_mcp_owner_ids(request: Any, web_principal_id: str) -> list[str]:
    if not mcp_web_link_enabled():
        return []
    web_id = require_principal_id(web_principal_id)
    store = getattr(getattr(request, "app", None).state, "principal_link_store", None)
    if store is None:
        return []
    return list(store.mcp_principals_for_web(web_id))


def browser_asset_owner_ids(request: Any, web_principal_id: str) -> list[str]:
    web_id = require_principal_id(web_principal_id)
    return [web_id, *linked_mcp_owner_ids(request, web_id)]
