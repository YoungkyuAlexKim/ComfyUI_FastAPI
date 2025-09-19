import logging
import json
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        msg = record.msg
        if isinstance(msg, dict):
            base.update(msg)
        else:
            base["message"] = record.getMessage()
        # Include common extras if present
        for key in ("request_id", "job_id", "owner_id", "path", "method", "status_code"):
            if hasattr(record, key):
                base[key] = getattr(record, key)
        try:
            return json.dumps(base, ensure_ascii=False)
        except Exception:
            # Fallback to repr if JSON fails
            return str(base)


def _parse_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def setup_logging(default_level: int = logging.INFO) -> logging.Logger:
    """Configure app logger from environment variables.

    ENV KEYS:
      - LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default INFO)
      - LOG_FORMAT: json|text (default json)
      - LOG_TO_FILE: true|false (default false)
      - LOG_FILE_PATH: logs/app.log (used when LOG_TO_FILE=true)
      - LOG_MAX_BYTES: integer bytes for rotation (default 1048576)
      - LOG_BACKUP_COUNT: integer number of rotated files (default 3)
    """
    logger = logging.getLogger("comfyui_app")
    if logger.handlers:
        return logger

    # Resolve level
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, default_level)
    logger.setLevel(level)

    # Formatter selection
    fmt_kind = os.getenv("LOG_FORMAT", "json").lower()
    if fmt_kind == "text":
        text_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        formatter = text_fmt
    else:
        formatter = JsonFormatter()

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Optional rotating file handler
    if _parse_bool(os.getenv("LOG_TO_FILE"), False):
        path = os.getenv("LOG_FILE_PATH", "logs/app.log")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        max_bytes = int(os.getenv("LOG_MAX_BYTES", "1048576"))  # 1MB
        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "3"))
        file_handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


