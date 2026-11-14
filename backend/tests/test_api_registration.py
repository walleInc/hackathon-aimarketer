from datetime import datetime, timezone

import pytest

from app.db import SessionLocal
from app.main import app
from app.models import Post
from tests.conftest import as_user


@pytest.mark.parametrize(("path", "method"), [
    ("/api/analytics/posts", "get"),
    ("/api/posts/{post_id}/metrics", "put"),
    ("/api/analytics/posts/recommendations", "post"),
    ("/api/agent/message/reference", "post"),
])
def test_existing_api_routes_remain_registered(path, method):
    assert method in app.openapi()["paths"][path]


@pytest.mark.parametrize("published_at", [None, datetime(2026, 1, 1, 12, 30)])
async def test_post_response_preserves_publication_time_and_schedule_state(client, env, published_at):
    async with SessionLocal() as session:
        post = Post(company_id=env["a"], text="Публикация", published_at=published_at, needs_reschedule=True)
        session.add(post)
        await session.commit()
        post_id = post.id

    response = await client.get(f"/api/posts/{post_id}", headers=as_user(100))
    assert response.status_code == 200
    data = response.json()
    assert data["needs_reschedule"] is True
    if published_at is None:
        assert data["published_at"] is None
    else:
        assert datetime.fromisoformat(data["published_at"]) == published_at.replace(tzinfo=timezone.utc)
