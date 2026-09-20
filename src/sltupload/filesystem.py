import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO

from sltupload.config import Settings
from sltupload.s3 import sanitize_catalog_name


class UploadError(Exception):
    """Raised when an image cannot be written to the filesystem."""


def sanitize_username(username: str) -> str:
    """Turn a Discord username into one safe filesystem path component."""
    normalized = unicodedata.normalize("NFKC", username).strip()
    normalized = normalized.replace("/", "-").replace("\\", "-")
    sanitized = re.sub(pattern=r"[^A-Za-z0-9._-]+", repl="-", string=normalized)
    sanitized = re.sub(pattern=r"-{2,}", repl="-", string=sanitized).strip("._-")
    return sanitized[:64] or "discord-user"


def upload_key(username: str, telescope: str, project: str) -> str:
    """Build the exact relative path used for member images."""
    safe_telescope = sanitize_catalog_name(value=telescope)
    safe_project = sanitize_catalog_name(value=project)
    if safe_telescope is None or safe_project is None:
        raise ValueError("Telescope and project names must be safe source folder names.")
    return f"{sanitize_username(username=username)}/{safe_telescope}/{safe_project}.jpg"


class ImageUploader:
    """Write image bytes below the configured filesystem path."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def upload(self, fileobj: BinaryIO, key: str) -> None:
        """Write a file without changing its bytes, replacing an existing path."""
        destination = self._destination(key=key)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open(mode="wb") as output:
                shutil.copyfileobj(fsrc=fileobj, fdst=output)
            now = time.time()
            os.utime(path=destination, times=(now, now))
        except OSError as exc:
            raise UploadError("Could not save the image to the configured upload path.") from exc

    def _destination(self, key: str) -> Path:
        relative_path = PurePosixPath(key)
        if relative_path.is_absolute() or not relative_path.parts or ".." in relative_path.parts or "\\" in key:
            raise UploadError("Invalid upload path.")

        try:
            root = self.settings.upload_path.resolve()
            destination = (root / Path(*relative_path.parts)).resolve()
            destination.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UploadError("Invalid upload path.") from exc
        return destination
