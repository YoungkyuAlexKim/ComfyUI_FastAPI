import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from app.asset_store import AssetStore
from app.config import UPLOAD_CONFIG
from app.services.asset_service import AssetService
from app.services.input_assets import (
    InputAssetError,
    decode_base64_image,
    normalize_input_image,
    register_input_image,
)


def _image_bytes(format_name: str = "PNG", *, size: tuple[int, int] = (12, 8)) -> bytes:
    mode = "RGBA" if format_name in {"PNG", "WEBP"} else "RGB"
    image = Image.new(mode, size, (10, 20, 30, 128) if mode == "RGBA" else (10, 20, 30))
    out = BytesIO()
    image.save(out, format=format_name)
    return out.getvalue()


class InputAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.output_root = root / "outputs"
        self.output_root.mkdir()
        self.store = AssetStore(str(root / "app.db"))
        self.service = AssetService(self.store, str(self.output_root))

    def tearDown(self):
        self.temp.cleanup()

    def test_png_jpeg_and_webp_are_decoded_and_normalized(self):
        for format_name, mime_type in (
            ("PNG", "image/png"),
            ("JPEG", "image/jpeg"),
            ("WEBP", "image/webp"),
        ):
            with self.subTest(format=format_name):
                normalized = normalize_input_image(
                    _image_bytes(format_name),
                    filename=f"reference.{format_name.lower()}",
                    content_type=mime_type,
                )
                self.assertTrue(normalized.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual((normalized.width, normalized.height), (12, 8))
                self.assertEqual(len(normalized.sha256), 64)

    def test_corrupt_png_and_oversized_dimensions_are_rejected(self):
        with self.assertRaisesRegex(InputAssetError, "corrupt or unreadable"):
            normalize_input_image(
                b"\x89PNG\r\n\x1a\nnot-an-image",
                filename="broken.png",
                content_type="image/png",
            )
        with mock.patch.dict(UPLOAD_CONFIG, {"inputs_max_pixels": 10}, clear=False):
            with self.assertRaisesRegex(InputAssetError, "pixel limit"):
                normalize_input_image(
                    _image_bytes("PNG", size=(4, 4)),
                    filename="large.png",
                    content_type="image/png",
                )

        with self.assertRaisesRegex(InputAssetError, "mime type does not match"):
            normalize_input_image(
                _image_bytes("JPEG"),
                filename="wrong.png",
                content_type="image/png",
            )

    def test_base64_data_url_is_validated(self):
        raw = _image_bytes("PNG")
        encoded = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        decoded, mime_type = decode_base64_image(encoded)
        self.assertEqual(decoded, raw)
        self.assertEqual(mime_type, "image/png")
        with self.assertRaisesRegex(InputAssetError, "valid base64"):
            decode_base64_image("%%%not-base64%%")

    def test_registration_is_owner_scoped_and_deduplicated(self):
        raw = _image_bytes("JPEG")
        first, first_duplicate = register_input_image(
            self.service,
            "mcp-ip-owner",
            raw,
            filename="../unsafe/reference.jpg",
            content_type="image/jpeg",
            deduplicate=True,
        )
        second, second_duplicate = register_input_image(
            self.service,
            "mcp-ip-owner",
            raw,
            filename="retry.jpg",
            content_type="image/jpeg",
            deduplicate=True,
        )
        other, other_duplicate = register_input_image(
            self.service,
            "mcp-ip-other",
            raw,
            filename="reference.jpg",
            content_type="image/jpeg",
            deduplicate=True,
        )

        self.assertFalse(first_duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertFalse(other_duplicate)
        self.assertNotEqual(first["asset_id"], other["asset_id"])
        self.assertEqual(first["metadata"]["original_filename"], "reference.jpg")
        self.assertTrue(Path(self.service.resolve_storage_path(first["storage_path"])).is_file())

    def test_concurrent_deduplicated_registration_creates_one_active_input(self):
        raw = _image_bytes("PNG")

        def register_once(_):
            return register_input_image(
                self.service,
                "mcp-ip-owner",
                raw,
                filename="concurrent.png",
                content_type="image/png",
                deduplicate=True,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(register_once, range(8)))

        self.assertEqual(len({row["asset_id"] for row, _ in results}), 1)
        self.assertEqual(sum(not duplicate for _, duplicate in results), 1)
        self.assertEqual(
            self.service.count_assets("mcp-ip-owner", kinds=("input",)),
            1,
        )

    def test_catalog_failure_removes_new_input_files(self):
        with mock.patch.object(self.store, "upsert", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                self.service.create_input_image("mcp-ip-owner", _image_bytes("PNG"), "input.png")
        remaining = [path for path in self.output_root.rglob("*") if path.is_file()]
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
