from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image

from app.asset_store import AssetStore
from app.auth.mcp_identity import (
    mcp_client_ip_allowed,
    parse_allowed_mcp_networks,
    principal_for_mcp_ip,
)
from app.principal_link_store import PrincipalLinkConflict, PrincipalLinkStore
from app.routers.images import router as images_router
from app.routers.inputs import router as inputs_router
from app.routers.principal_links import router as principal_links_router
from app.services.asset_service import AssetService


class McpIdentityTests(unittest.TestCase):
    def test_shared_ip_identity_and_allowlist_are_deterministic(self):
        self.assertEqual(principal_for_mcp_ip("10.0.0.8"), principal_for_mcp_ip("10.0.0.8"))
        self.assertNotEqual(principal_for_mcp_ip("10.0.0.8"), principal_for_mcp_ip("10.0.0.9"))
        self.assertTrue(mcp_client_ip_allowed("10.0.0.8", "10.0.0.0/24"))
        self.assertFalse(mcp_client_ip_allowed("10.0.1.8", "10.0.0.0/24"))
        self.assertEqual(len(parse_allowed_mcp_networks("10.0.0.0/24,127.0.0.1/32")), 2)
        with self.assertRaises(ValueError):
            parse_allowed_mcp_networks("not-a-cidr")


class PrincipalLinkStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "app.db")
        self.store = PrincipalLinkStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_link_is_persistent_idempotent_and_reversible(self):
        first = self.store.link("anon-web-a", "mcp-ip-workspace-a", client_ip="10.0.0.8")
        second = self.store.link("anon-web-a", "mcp-ip-workspace-a", client_ip="10.0.0.8")
        reopened = PrincipalLinkStore(self.db_path)

        self.assertEqual(first["created_at"], second["created_at"])
        self.assertTrue(reopened.is_linked("anon-web-a", "mcp-ip-workspace-a"))
        self.assertEqual(reopened.mcp_principals_for_web("anon-web-a"), ["mcp-ip-workspace-a"])
        self.assertTrue(reopened.unlink("anon-web-a", "mcp-ip-workspace-a", client_ip="10.0.0.8"))
        self.assertFalse(reopened.is_linked("anon-web-a", "mcp-ip-workspace-a"))
        self.assertEqual(
            [event["event_type"] for event in reopened.recent_events(10)],
            ["unlinked", "link_verified", "linked"],
        )

    def test_link_never_transfers_an_existing_workspace(self):
        self.store.link("anon-web-a", "mcp-ip-workspace-a", client_ip="10.0.0.8")
        with self.assertRaises(PrincipalLinkConflict):
            self.store.link("anon-web-b", "mcp-ip-workspace-a", client_ip="10.0.0.8")
        self.assertEqual(self.store.web_principal_for_mcp("mcp-ip-workspace-a"), "anon-web-a")
        self.assertFalse(self.store.unlink("anon-web-b", "mcp-ip-workspace-a"))

    def test_browser_can_retain_historical_ip_workspaces(self):
        self.store.link("anon-web-a", "mcp-ip-workspace-a")
        self.store.link("anon-web-a", "mcp-ip-workspace-b")
        self.assertEqual(
            self.store.mcp_principals_for_web("anon-web-a"),
            ["mcp-ip-workspace-a", "mcp-ip-workspace-b"],
        )


class LinkedAssetPaginationTests(unittest.TestCase):
    def test_multi_owner_gallery_keeps_each_group_together(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AssetStore(str(Path(directory) / "catalog.db"))

            def add(asset_id: str, owner_id: str, created_at: float, group_id: str | None = None):
                store.upsert(
                    {
                        "asset_id": asset_id,
                        "owner_id": owner_id,
                        "kind": "image",
                        "status": "active",
                        "storage_path": f"users/{owner_id}/{asset_id}.png",
                        "created_at": created_at,
                        "group_id": group_id,
                        "metadata": {"id": asset_id, "game_ui_group_id": group_id},
                    }
                )

            add("web-new", "anon-web-a", 30)
            for index in range(4):
                add(f"mcp-cell-{index}", "mcp-ip-workspace-a", 20 - index, "mcp-group")
            add("web-old", "anon-web-a", 10)

            first, first_page = store.list_group_preserving_page_for_owners(
                ("anon-web-a", "mcp-ip-workspace-a"), kind="image", page=1, size=3
            )
            second, second_page = store.list_group_preserving_page_for_owners(
                ("anon-web-a", "mcp-ip-workspace-a"), kind="image", page=2, size=3
            )

            self.assertEqual([row["asset_id"] for row in first], ["web-new"])
            self.assertEqual({row["asset_id"] for row in second}, {f"mcp-cell-{i}" for i in range(4)})
            self.assertEqual(first_page["total"], 6)
            self.assertEqual(second_page["total_pages"], 3)


class PrincipalLinkApiTests(unittest.TestCase):
    def test_same_ip_link_surfaces_and_copies_mcp_image_without_takeover(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ",
            {"MCP_WEB_LINK_ENABLED": "true", "MCP_ALLOWED_CLIENT_CIDRS": ""},
            clear=False,
        ):
            root = Path(directory)
            output_root = root / "outputs"
            output_root.mkdir()
            db_path = str(root / "app.db")
            asset_service = AssetService(AssetStore(db_path), str(output_root))
            link_store = PrincipalLinkStore(db_path)
            app = FastAPI()

            @app.middleware("http")
            async def test_browser_principal(request: Request, call_next):
                request.state.principal_id = request.headers.get("x-test-web", "anon-web-a")
                return await call_next(request)

            app.include_router(images_router)
            app.include_router(inputs_router)
            app.include_router(principal_links_router)
            app.state.asset_service = asset_service
            app.state.principal_link_store = link_store

            mcp_owner = principal_for_mcp_ip("testclient")
            asset_id = "linked-mcp-image"
            asset_dir = output_root / "users" / mcp_owner / "2026" / "08" / "17"
            asset_dir.mkdir(parents=True)
            png_path = asset_dir / f"{asset_id}.png"
            meta_path = asset_dir / f"{asset_id}.json"
            Image.new("RGBA", (8, 6), (20, 40, 60, 180)).save(png_path, format="PNG")
            metadata = {
                "id": asset_id,
                "owner": mcp_owner,
                "kind": "image",
                "mime": "image/png",
                "created_at": "2026-08-17T00:00:00+00:00",
                "status": "active",
                "workflow_id": "RMBG2",
            }
            meta_path.write_text(json.dumps(metadata), encoding="utf-8")
            asset_service.register(
                owner_id=mcp_owner,
                kind="image",
                media_path=str(png_path),
                metadata_path=str(meta_path),
                metadata=metadata,
            )

            with TestClient(app, headers={"x-test-web": "anon-web-a"}) as client:
                self.assertEqual(client.get("/api/v1/images").json()["total"], 0)
                available = client.get("/api/v1/principal-links/mcp").json()
                self.assertEqual(available["state"], "available")
                self.assertEqual(available["candidate_image_count"], 1)

                linked = client.post(
                    "/api/v1/principal-links/mcp",
                    json={"mcp_principal_id": "mcp-ip-spoofed-target"},
                )
                self.assertEqual(linked.status_code, 200)
                gallery = client.get("/api/v1/images?preserve_groups=true").json()
                self.assertEqual(gallery["total"], 1)
                self.assertTrue(gallery["items"][0]["linked_from_mcp"])

                denied_delete = client.post(
                    f"/api/v1/images/{asset_id}/delete",
                    headers={"x-test-web": "anon-web-b"},
                )
                self.assertEqual(denied_delete.status_code, 404)
                self.assertEqual(asset_service.get(mcp_owner, asset_id)["status"], "active")

                deleted = client.post(f"/api/v1/images/{asset_id}/delete")
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertEqual(client.get("/api/v1/images").json()["total"], 0)
                self.assertEqual(asset_service.get(mcp_owner, asset_id)["status"], "trash")
                self.assertEqual(json.loads(meta_path.read_text(encoding="utf-8"))["status"], "trash")

                denied_restore = client.post(
                    f"/api/v1/images/{asset_id}/restore",
                    headers={"x-test-web": "anon-web-b"},
                )
                self.assertEqual(denied_restore.status_code, 404)
                restored = client.post(f"/api/v1/images/{asset_id}/restore")
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(client.get("/api/v1/images").json()["total"], 1)
                self.assertEqual(asset_service.get(mcp_owner, asset_id)["status"], "active")
                self.assertEqual(json.loads(meta_path.read_text(encoding="utf-8"))["status"], "active")

                copied = client.post(
                    "/api/v1/inputs/copy",
                    json={"source": "generated", "id": asset_id},
                )
                self.assertEqual(copied.status_code, 200, copied.text)
                self.assertNotEqual(copied.json()["id"], asset_id)

                conflict = client.get(
                    "/api/v1/principal-links/mcp",
                    headers={"x-test-web": "anon-web-b"},
                ).json()
                takeover = client.post(
                    "/api/v1/principal-links/mcp",
                    headers={"x-test-web": "anon-web-b"},
                    json={},
                )
                self.assertEqual(conflict["state"], "conflict")
                self.assertEqual(conflict["candidate_image_count"], 0)
                self.assertEqual(takeover.status_code, 409)

                unlinked = client.delete("/api/v1/principal-links/mcp")
                self.assertEqual(unlinked.status_code, 200)
                self.assertEqual(client.get("/api/v1/images").json()["total"], 0)
                self.assertEqual(client.post(f"/api/v1/images/{asset_id}/delete").status_code, 404)
                self.assertIsNotNone(asset_service.get(mcp_owner, asset_id))

    def test_linked_mcp_game_ui_group_can_be_trashed_and_restored_as_one_unit(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ",
            {"MCP_WEB_LINK_ENABLED": "true", "MCP_ALLOWED_CLIENT_CIDRS": ""},
            clear=False,
        ):
            root = Path(directory)
            output_root = root / "outputs"
            output_root.mkdir()
            db_path = str(root / "app.db")
            store = AssetStore(db_path)
            asset_service = AssetService(store, str(output_root))
            link_store = PrincipalLinkStore(db_path)
            app = FastAPI()

            @app.middleware("http")
            async def test_browser_principal(request: Request, call_next):
                request.state.principal_id = request.headers.get("x-test-web", "anon-web-a")
                return await call_next(request)

            app.include_router(images_router)
            app.include_router(principal_links_router)
            app.state.asset_service = asset_service
            app.state.principal_link_store = link_store

            mcp_owner = principal_for_mcp_ip("testclient")
            group_id = "linked-mcp-game-ui"
            child_ids = ["linked-mcp-cell-1", "linked-mcp-cell-2"]
            store.upsert_group({
                "group_id": group_id,
                "owner_id": mcp_owner,
                "kind": "game_ui_group",
                "status": "active",
                "manifest_path": None,
                "created_at": 2,
                "metadata": {"id": group_id, "kind": "game_ui_group", "status": "active"},
            })
            for index, child_id in enumerate(child_ids):
                store.upsert({
                    "asset_id": child_id,
                    "owner_id": mcp_owner,
                    "kind": "image",
                    "status": "active",
                    "storage_path": f"users/{mcp_owner}/{child_id}.png",
                    "group_id": group_id,
                    "created_at": 2 - index,
                    "metadata": {
                        "id": child_id,
                        "status": "active",
                        "game_ui_group_id": group_id,
                    },
                })

            with TestClient(app, headers={"x-test-web": "anon-web-a"}) as client:
                self.assertEqual(client.post("/api/v1/principal-links/mcp", json={}).status_code, 200)
                self.assertEqual(client.get("/api/v1/images?preserve_groups=true").json()["total"], 2)

                denied = client.post(
                    f"/api/v1/game-ui-groups/{group_id}/delete",
                    headers={"x-test-web": "anon-web-b"},
                )
                self.assertEqual(denied.status_code, 404)
                deleted = client.post(f"/api/v1/game-ui-groups/{group_id}/delete")
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertEqual(client.get("/api/v1/images").json()["total"], 0)
                self.assertEqual({store.get(child_id)["status"] for child_id in child_ids}, {"trash"})
                self.assertEqual(store.get_group(group_id)["status"], "trash")

                restored = client.post(f"/api/v1/game-ui-groups/{group_id}/restore")
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(client.get("/api/v1/images?preserve_groups=true").json()["total"], 2)
                self.assertEqual({store.get(child_id)["status"] for child_id in child_ids}, {"active"})
                self.assertEqual(store.get_group(group_id)["status"], "active")


if __name__ == "__main__":
    unittest.main()
