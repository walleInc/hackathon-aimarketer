import uuid
from pathlib import Path

from .config import settings


def media_path(url: str) -> Path:
    """URL вида /media/cards/x.png -> путь на диске."""
    return Path(settings.media_dir) / url.removeprefix("/media/")


def new_media_file(subdir: str, ext: str) -> tuple[Path, str]:
    """Возвращает (путь на диске, URL) для нового файла."""
    name = f"{uuid.uuid4().hex}{ext}"
    path = Path(settings.media_dir) / subdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, f"/media/{subdir}/{name}"
