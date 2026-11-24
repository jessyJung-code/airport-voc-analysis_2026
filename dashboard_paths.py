"""Local source path configuration for monthly rebuilding."""
import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SOURCE_DIR = Path(json.loads((APP_DIR / "dashboard_paths.json").read_text(encoding="utf-8"))["source_directory"])
