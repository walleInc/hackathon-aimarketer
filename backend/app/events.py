"""Pub/Sub: события между экземплярами приложения (канал aim:events)."""
import asyncio
import json
import logging
from typing import Awaitable, Callable

from . import cache

log = logging.getLogger(__name__)
CHANNEL = cache.PREFIX + "events"
Handler = Callable[[str, dict], Awaitable[None]]
_handlers: list[Handler] = []


def on_event(handler: Handler) -> Handler:
    _handlers.append(handler)
    return handler


async def publish(event: str, **data) -> None:
    try:
        await cache.get_redis().publish(CHANNEL, json.dumps({"event": event, **data}, ensure_ascii=False))
    except Exception:
        log.warning("publish %s failed", event, exc_info=True)


async def listen() -> None:
    """Слушает канал и раздаёт события обработчикам; переподключается при обрыве."""
    while True:
        try:
            pubsub = cache.get_redis().pubsub()
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                payload = json.loads(msg["data"])
                event = payload.pop("event")
                for h in _handlers:
                    try:
                        await h(event, payload)
                    except Exception:
                        log.exception("event handler failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("pub/sub отключён, повтор через 5 с", exc_info=True)
            await asyncio.sleep(5)
