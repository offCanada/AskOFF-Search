# ruff: noqa: E402
import sys
from pathlib import Path

_backend_root = str(Path(__file__).resolve().parent)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from api.app import app, create_app

__all__ = ["app", "create_app"]
