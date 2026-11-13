"""Файлы контекста организации: лежат в Yandex S3 по пути {organization_id}/{файл}, текст берётся оттуда при запросе к AI."""
import asyncio
import io
import logging

from . import cache, events, storage
from .config import settings

log = logging.getLogger(__name__)

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm"}
ALLOWED_EXT = TEXT_EXT | {".pdf", ".docx"}
FILE_TEXT_TTL = 7 * 86400  # текст привязан к ETag файла: изменился файл — новый ключ


class UnsupportedFile(Exception):
    pass


def ext_of(name: str) -> str:
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _extract_sync(name: str, data: bytes) -> str:
    ext = ext_of(name)
    if ext in TEXT_EXT:
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if ext == ".docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        parts += [" | ".join(c.text for c in row.cells) for t in doc.tables for row in t.rows]
        return "\n".join(parts)
    raise UnsupportedFile(f"Формат {ext or name} не поддерживается (доступно: {', '.join(sorted(ALLOWED_EXT))})")


async def extract_text(name: str, data: bytes) -> str:
    return (await asyncio.to_thread(_extract_sync, name, data)).strip()


async def file_text(f: storage.StoredFile) -> str:
    """Текст файла из кэша Redis (ключ включает ETag) или из S3 с извлечением."""
    async def load() -> str:
        return await extract_text(f.name, await storage.get(f.key))

    return await cache.cached(f"filetext:{f.key}:{f.etag}", load, ttl=FILE_TEXT_TTL)


async def _build_files_context(org_id: int) -> str:
    files = await storage.list_files(org_id)
    parts: list[str] = []
    for f in sorted(files, key=lambda x: x.name):
        if ext_of(f.name) not in ALLOWED_EXT or f.size > settings.max_context_file_mb * 1024 * 1024:
            continue
        try:
            text = await file_text(f)
        except Exception:
            log.warning("не удалось прочитать %s", f.key, exc_info=True)
            continue
        if text:
            parts.append(f"## Файл: {f.name}\n{text}")
    return "\n\n".join(parts)[: settings.context_files_limit]


async def load_context(org_id: int) -> str:
    """Текст всех файлов организации для запроса к AI. Сбой хранилища не ломает ответ агента."""
    if not storage.enabled():
        return ""
    try:
        return await cache.cached(f"ctx:files:{org_id}", lambda: _build_files_context(org_id))
    except Exception:
        log.warning("файлы контекста организации %s недоступны", org_id, exc_info=True)
        return ""


async def invalidate(org_id: int) -> None:
    """Сбрасывает кэш контекста организации на всех экземплярах приложения."""
    await cache.invalidate(f"ctx:files:{org_id}", f"ctx:prompt:{org_id}")
    await events.publish("context.changed", org_id=org_id)


async def upload(org_id: int, filename: str, data: bytes, content_type: str) -> dict:
    name = storage.safe_name(filename)
    if ext_of(name) not in ALLOWED_EXT:
        raise UnsupportedFile(f"Формат {ext_of(name) or name} не поддерживается (доступно: {', '.join(sorted(ALLOWED_EXT))})")
    if len(data) > settings.max_context_file_mb * 1024 * 1024:
        raise UnsupportedFile(f"Файл больше {settings.max_context_file_mb} МБ")
    await storage.put(org_id, name, data, content_type)
    await invalidate(org_id)
    from . import jobs  # отложенный импорт: jobs использует этот модуль

    await jobs.enqueue("document-processing", "extract", {"company_id": org_id, "filename": name})
    return {"name": name, "key": storage.key_for(org_id, name), "size": len(data)}


async def remove(org_id: int, filename: str) -> None:
    await storage.delete(org_id, filename)
    await invalidate(org_id)


async def list_for_api(org_id: int) -> list[dict]:
    files = await storage.list_files(org_id)
    return [
        {"name": f.name, "size": f.size, "modified": f.modified.isoformat(), "supported": ext_of(f.name) in ALLOWED_EXT}
        for f in sorted(files, key=lambda x: x.name)
    ]

