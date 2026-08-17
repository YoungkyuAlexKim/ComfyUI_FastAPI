import io
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.logging_utils import JsonFormatter, ResilientRotatingFileHandler


class ResilientRotatingFileHandlerTests(unittest.TestCase):
    def test_delays_opening_the_configured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            handler = ResilientRotatingFileHandler(
                str(path), maxBytes=1024, backupCount=1, encoding="utf-8"
            )
            try:
                self.assertIsNone(handler.stream)
                self.assertFalse(path.exists())
            finally:
                handler.close()

    def test_rotation_lock_falls_back_without_logging_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            handler = ResilientRotatingFileHandler(
                str(path), maxBytes=1, backupCount=1, encoding="utf-8"
            )
            handler.setFormatter(JsonFormatter())
            stderr = io.StringIO()
            record = logging.LogRecord(
                "test",
                logging.INFO,
                __file__,
                1,
                {"event": "rotation_test"},
                (),
                None,
            )
            try:
                handler.emit(record)
                with patch.object(
                    handler,
                    "rotate",
                    side_effect=PermissionError(32, "file is used by another process"),
                ), patch("sys.stderr", stderr):
                    handler.emit(record)
                fallback = Path(handler.baseFilename)
                self.assertNotEqual(fallback, path.resolve())
                self.assertIn(f"pid-{os.getpid()}", fallback.name)
                self.assertIn("rotation_test", fallback.read_text(encoding="utf-8"))
                self.assertIn("continuing in", stderr.getvalue())
                self.assertNotIn("Logging error", stderr.getvalue())
            finally:
                handler.close()


if __name__ == "__main__":
    unittest.main()
