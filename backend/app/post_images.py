"""Проверка загруженной картинки и сохранение в собственном формате PNG."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from . import branding

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def prepare_upload(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Загрузите изображение размером до 10 МБ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Поддерживаются PNG, JPEG и WebP")
                if source.width * source.height > 20_000_000:
                    raise ValueError("Изображение должно содержать не более 20 млн пикселей")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2560, 2560))
                return image.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Не удалось прочитать изображение. Используйте PNG, JPEG или WebP") from exc


def save_upload(data: bytes) -> str:
    return branding.save_image(prepare_upload(data), "uploads")


def reference_bytes(data: bytes) -> bytes:
    image = prepare_upload(data)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
