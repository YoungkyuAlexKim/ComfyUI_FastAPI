"""Runtime wiring for the shared AssetService."""

from __future__ import annotations

from typing import Optional

from .asset_service import AssetService


_asset_service: Optional[AssetService] = None


def configure_asset_service(service: Optional[AssetService]) -> None:
    """Set or explicitly clear the process-wide asset service binding."""

    global _asset_service
    _asset_service = service


def get_asset_service(*, required: bool = False) -> Optional[AssetService]:
    if required and _asset_service is None:
        raise RuntimeError("AssetService is not configured")
    return _asset_service
