import os
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO

from PIL import Image

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


def is_valid_jpeg(fileobj: BinaryIO) -> bool:
    """Return whether a file contains a decodable JPEG image."""
    try:
        fileobj.seek(0)
        with Image.open(fp=fileobj) as image:
            if image.format != "JPEG":
                return False
            image.verify()
    except (OSError, SyntaxError, ValueError):
        return False

    try:
        fileobj.seek(0)
    except (OSError, ValueError):
        return False
    return True


class ImageUploader:
    """Write image bytes below the configured filesystem path."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def upload(self, fileobj: BinaryIO, key: str) -> None:
        """Write a file without changing its bytes, replacing an existing path."""
        destination = self._destination(key=key)
        temporary_path: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                shutil.copyfileobj(fsrc=fileobj, fdst=output)
                output.flush()
                os.fsync(output.fileno())
            now = time.time()
            os.utime(path=temporary_path, times=(now, now))
            os.replace(src=temporary_path, dst=destination)
            temporary_path = None
        except OSError as exc:
            raise UploadError("Could not save the image to the configured upload path.") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

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
