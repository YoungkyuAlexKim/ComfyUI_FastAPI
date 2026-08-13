import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageDraw

from app.asset_store import AssetStore
from app.services import media_store
from app.services import asset_runtime
from app.services import openrouter_client
from app.services.asset_service import AssetService
from app.services.generation import run_generation_processor
from app.services.game_ui_assets import (
    build_game_ui_generation_prompt,
    normalize_game_ui_options,
    process_game_ui_sheet,
    split_sheet_grid,
    split_sheet_2x2,
)
from app.workflow_configs import WORKFLOW_CONFIGS


def _synthetic_sheet(size=256):
    image = Image.new("RGB", (size, size), (3, 248, 5))
    draw = ImageDraw.Draw(image)
    half = size // 2
    colors = [(220, 40, 50), (40, 110, 230), (245, 175, 30), (145, 55, 210)]
    for index, color in enumerate(colors):
        col = index % 2
        row = index // 2
        left = col * half + 24
        top = row * half + 24
        right = (col + 1) * half - 24
        bottom = (row + 1) * half - 24
        draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=color)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _synthetic_horizontal_sheet(size=256):
    image = Image.new("RGB", (size, size), (3, 248, 5))
    draw = ImageDraw.Draw(image)
    half = size // 2
    for index in range(4):
        col = index % 2
        row = index // 2
        left = col * half + 12
        top = row * half + 45
        right = (col + 1) * half - 12
        bottom = (row + 1) * half - 45
        draw.rounded_rectangle((left, top, right, bottom), radius=10, fill=(220, 70, 45))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _synthetic_grid(grid_size, width=256, height=None):
    height = height or width
    image = Image.new("RGB", (width, height), (3, 248, 5))
    draw = ImageDraw.Draw(image)
    colors = []
    for index in range(grid_size * grid_size):
        color = (
            24 + (index * 47) % 210,
            20 + (index * 83) % 210,
            28 + (index * 109) % 210,
        )
        colors.append(color)
        col = index % grid_size
        row = index // grid_size
        x0 = (width * col) // grid_size
        x1 = (width * (col + 1)) // grid_size
        y0 = (height * row) // grid_size
        y1 = (height * (row + 1)) // grid_size
        margin = max(2, min(x1 - x0, y1 - y0) // 6)
        draw.rectangle((x0 + margin, y0 + margin, x1 - margin - 1, y1 - margin - 1), fill=color)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue(), colors


class GameUiAssetTests(unittest.TestCase):
    def test_options_are_clamped_to_mvp_contract(self):
        self.assertEqual(normalize_game_ui_options("opaque").background_mode, "opaque")
        self.assertEqual(normalize_game_ui_options("unknown").background_mode, "transparent")
        self.assertEqual(normalize_game_ui_options("transparent", "3x3").asset_count, 9)
        self.assertEqual(normalize_game_ui_options("transparent", "4×4").grid, "4x4")
        self.assertEqual(normalize_game_ui_options("transparent", "unsupported").grid, "2x2")

    def test_prompt_supports_text_only_and_optional_references(self):
        options = normalize_game_ui_options("transparent")
        text_only = build_game_ui_generation_prompt("얼음 스킬 아이콘", options)
        referenced = build_game_ui_generation_prompt("얼음 스킬 아이콘", options, reference_count=2)
        self.assertIn("exactly four equal cells", text_only)
        self.assertIn("#00FF00", text_only)
        self.assertIn("None are attached", text_only)
        self.assertIn("Use the attached images", referenced)
        self.assertIn("Do not force it into a predefined", referenced)
        self.assertIn("Do not invent words", referenced)

        sixteen = build_game_ui_generation_prompt(
            "얼음 스킬 아이콘",
            normalize_game_ui_options("opaque", "4x4"),
        )
        self.assertIn("exactly sixteen equal cells", sixteen)
        self.assertIn("4 columns by 4 rows", sixteen)
        self.assertIn("finished 4x4 sheet", sixteen)

    def test_sheet_is_split_in_reading_order(self):
        tiles = split_sheet_2x2(_synthetic_sheet())
        self.assertEqual(len(tiles), 4)
        centers = [tile.getpixel((tile.width // 2, tile.height // 2)) for tile in tiles]
        self.assertEqual(centers, [(220, 40, 50), (40, 110, 230), (245, 175, 30), (145, 55, 210)])

    def test_all_supported_grids_split_in_reading_order_without_dropping_pixels(self):
        for grid_size in (2, 3, 4):
            with self.subTest(grid_size=grid_size):
                sheet, colors = _synthetic_grid(grid_size, width=257, height=259)
                tiles = split_sheet_grid(sheet, f"{grid_size}x{grid_size}")
                self.assertEqual(len(tiles), grid_size * grid_size)
                centers = [tile.getpixel((tile.width // 2, tile.height // 2)) for tile in tiles]
                self.assertEqual(centers, colors)
                self.assertEqual(sum(tile.width for tile in tiles[:grid_size]), 257)
                self.assertEqual(sum(tiles[row * grid_size].height for row in range(grid_size)), 259)

    def test_transparent_assets_and_all_derivative_sizes_are_created(self):
        options = normalize_game_ui_options("transparent")
        assets = process_game_ui_sheet(_synthetic_sheet(), options)
        self.assertEqual(len(assets), 4)
        self.assertEqual(set(assets[0].size_pngs), {"32", "64", "128", "256"})
        with Image.open(BytesIO(assets[0].master_png)) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertGreater(image.getchannel("A").getbbox()[2], 0)
        with Image.open(BytesIO(assets[0].size_pngs["64"])) as image:
            self.assertEqual(image.size, (64, 64))

    def test_derivatives_preserve_the_generated_elements_natural_ratio(self):
        options = normalize_game_ui_options("transparent")
        asset = process_game_ui_sheet(_synthetic_horizontal_sheet(), options)[0]
        self.assertGreater(asset.master_width, asset.master_height * 2)
        self.assertEqual(max(asset.size_dimensions["64"]), 64)
        self.assertGreater(asset.size_dimensions["64"][0], asset.size_dimensions["64"][1] * 2)

    def test_processing_returns_one_asset_per_selected_grid_cell(self):
        for grid_size in (2, 3, 4):
            with self.subTest(grid_size=grid_size):
                sheet, _ = _synthetic_grid(grid_size)
                options = normalize_game_ui_options("opaque", f"{grid_size}x{grid_size}")
                assets = process_game_ui_sheet(sheet, options)
                self.assertEqual(len(assets), grid_size * grid_size)
                self.assertEqual([asset.index for asset in assets], list(range(1, grid_size * grid_size + 1)))

    def test_group_storage_keeps_four_gallery_children_and_one_zip(self):
        sheet = _synthetic_sheet()
        options = normalize_game_ui_options("transparent")
        assets = process_game_ui_sheet(sheet, options)
        req = SimpleNamespace(
            workflow_id="GameUI_Elements",
            aspect_ratio="square",
            image_size="2K",
            image_model="openai/gpt-image-2",
            image_quality="medium",
            seed=123,
            user_prompt="server prompt",
            game_ui_original_prompt="붉은 화염 스킬 아이콘",
            game_ui_background_mode="transparent",
            input_image_id=None,
            input_image_ids=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = AssetService(AssetStore(os.path.join(tmp, "catalog.db")), tmp)
            with mock.patch.object(media_store, "OUTPUT_DIR", tmp), mock.patch.object(
                asset_runtime, "_asset_service", service
            ):
                first_url, group = media_store._save_game_ui_group("tester", sheet, assets, req, "test")
                gallery_items = media_store._gather_user_images("tester")
                self.assertEqual(len(gallery_items), 4)
                self.assertEqual(group["count"], 4)
                self.assertEqual(len(group["items"]), 4)
                self.assertEqual(first_url, group["items"][0]["url"])
                self.assertTrue(all(item["meta"]["game_ui_group_id"] == group["id"] for item in gallery_items))

                zip_relative = group["download_url"].removeprefix("/outputs/")
                zip_path = os.path.join(tmp, *zip_relative.split("/"))
                self.assertTrue(os.path.isfile(zip_path))
                with zipfile.ZipFile(zip_path, "r") as archive:
                    names = set(archive.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("masters/cell_01.png", names)
                    self.assertIn("sizes/64x64/cell_04.png", names)

                manifest_relative = group["sheet_url"].removeprefix("/outputs/")
                source_path = os.path.join(tmp, *manifest_relative.split("/"))
                manifest_path = os.path.join(os.path.dirname(source_path), "manifest.json")
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    saved_group = json.load(handle)
                self.assertEqual(saved_group["prompt"], "붉은 화염 스킬 아이콘")
                self.assertEqual(service.store.group_stats(), {"game_ui_group:active": 1})
                self.assertEqual(service.count_media("tester", "image"), 4)

    def test_group_storage_uses_selected_grid_in_catalog_manifest_and_zip(self):
        sheet, _ = _synthetic_grid(3)
        options = normalize_game_ui_options("opaque", "3x3")
        assets = process_game_ui_sheet(sheet, options)
        req = SimpleNamespace(
            workflow_id="GameUI_Elements",
            aspect_ratio="square",
            image_size="2K",
            image_model="openai/gpt-image-2",
            image_quality="medium",
            seed=456,
            user_prompt="server prompt",
            game_ui_original_prompt="금속 버튼",
            game_ui_background_mode="opaque",
            game_ui_grid="3x3",
            input_image_id=None,
            input_image_ids=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = AssetService(AssetStore(os.path.join(tmp, "catalog.db")), tmp)
            with mock.patch.object(media_store, "OUTPUT_DIR", tmp), mock.patch.object(
                asset_runtime, "_asset_service", service
            ):
                _, group = media_store._save_game_ui_group("tester", sheet, list(reversed(assets)), req, "test")
                gallery_items = media_store._gather_user_images("tester")
                self.assertEqual(group["grid"], "3x3")
                self.assertEqual((group["columns"], group["rows"]), (3, 3))
                self.assertEqual(group["count"], 9)
                self.assertEqual(len(gallery_items), 9)
                self.assertTrue(all(item["meta"]["game_ui_grid"] == "3x3" for item in gallery_items))
                self.assertTrue(all(item["meta"]["game_ui_cell_count"] == 9 for item in gallery_items))
                self.assertEqual(len({item["meta"]["created_at"] for item in gallery_items}), 1)
                zip_relative = group["download_url"].removeprefix("/outputs/")
                with zipfile.ZipFile(os.path.join(tmp, *zip_relative.split("/")), "r") as archive:
                    self.assertIn("masters/cell_09.png", archive.namelist())
                    self.assertEqual(archive.read("masters/cell_01.png"), assets[0].master_png)

    def test_group_storage_compensates_files_when_atomic_catalog_registration_fails(self):
        sheet = _synthetic_sheet()
        options = normalize_game_ui_options("transparent")
        assets = process_game_ui_sheet(sheet, options)
        req = SimpleNamespace(
            workflow_id="GameUI_Elements",
            aspect_ratio="square",
            image_size="2K",
            image_model="openai/gpt-image-2",
            image_quality="medium",
            seed=789,
            user_prompt="server prompt",
            game_ui_original_prompt="실패 보상 테스트",
            game_ui_background_mode="transparent",
            game_ui_grid="2x2",
            input_image_id=None,
            input_image_ids=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = AssetService(AssetStore(os.path.join(tmp, "catalog.db")), tmp)
            with mock.patch.object(media_store, "OUTPUT_DIR", tmp), mock.patch.object(
                asset_runtime, "_asset_service", service
            ), mock.patch.object(
                service.store,
                "upsert_asset_group_bundle",
                side_effect=RuntimeError("simulated catalog failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated catalog failure"):
                    media_store._save_game_ui_group("tester", sheet, assets, req, "test")

            self.assertEqual(service.count_media("tester", "image"), 0)
            self.assertEqual(service.store.group_stats(), {})
            user_files = [path for path in (Path(tmp) / "users").rglob("*") if path.is_file()]
            self.assertEqual(user_files, [])

    def test_workflow_is_locked_to_gpt_image_2(self):
        config = WORKFLOW_CONFIGS["GameUI_Elements"]
        self.assertEqual(config["openrouter"]["allowed_models"], ["openai/gpt-image-2"])
        self.assertEqual(config["openrouter"]["default_resolution"], "2K")
        self.assertEqual(config["ui"]["gameUiTool"]["variantCount"], 4)
        self.assertEqual(
            [grid["id"] for grid in config["ui"]["gameUiTool"]["supportedGrids"]],
            ["2x2", "3x3", "4x4"],
        )
        self.assertEqual(len(config["ui"]["promptTemplates"]), 12)
        self.assertEqual(config["ui"]["gameUiTool"]["promptPresetInitialCount"], 6)
        self.assertNotIn("assetType", config["ui"]["gameUiTool"]["defaults"])
        self.assertNotIn("targetSize", config["ui"]["gameUiTool"]["defaults"])

    def test_generation_pipeline_accepts_optional_reference_and_returns_group(self):
        sheet, _ = _synthetic_grid(3)
        with tempfile.TemporaryDirectory() as tmp:
            service = AssetService(AssetStore(os.path.join(tmp, "catalog.db")), tmp)
            with mock.patch.object(media_store, "OUTPUT_DIR", tmp), mock.patch.object(
                asset_runtime, "_asset_service", service
            ):
                input_path, input_meta_path = media_store._save_input_image_and_meta("tester", sheet, "reference.png")
                with open(input_meta_path, "r", encoding="utf-8") as handle:
                    input_id = json.load(handle)["id"]

                job = SimpleNamespace(
                    id="job-game-ui",
                    owner_id="tester",
                    payload={
                        "workflow_id": "GameUI_Elements",
                        "user_prompt": "바다 마법 스킬 아이콘",
                        "aspect_ratio": "square",
                        "seed": 99,
                        "image_size": None,
                        "image_model": None,
                        "image_quality": None,
                        "input_image_ids": [input_id],
                        "game_ui_background_mode": "transparent",
                        "game_ui_grid": "3x3",
                    },
                    result={},
                )
                progress = []
                cancel_handles = []
                with mock.patch.object(openrouter_client, "generate_image", return_value=sheet) as generate:
                    run_generation_processor(job, progress.append, cancel_handles.append)

                self.assertIn("asset_group", job.result)
                self.assertEqual(job.result["asset_group"]["count"], 9)
                self.assertEqual(job.result["asset_group"]["grid"], "3x3")
                self.assertEqual(job.result["asset_group"]["prompt"], "바다 마법 스킬 아이콘")
                self.assertEqual(progress[-1], 100)
                kwargs = generate.call_args.kwargs
                self.assertEqual(kwargs["model"], "openai/gpt-image-2")
                self.assertEqual(kwargs["resolution"], "2K")
                self.assertEqual(kwargs["quality"], "medium")
                self.assertEqual(len(kwargs["images"]), 1)
                self.assertIn("Use the attached images", kwargs["prompt"])
                self.assertEqual(service.count_media("tester", "input"), 1)
                self.assertEqual(service.count_media("tester", "image"), 9)
                self.assertEqual(service.store.group_stats(), {"game_ui_group:active": 1})


if __name__ == "__main__":
    unittest.main()
