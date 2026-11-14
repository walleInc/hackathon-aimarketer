"""Bounded context assembled from persistent, tenant-scoped records (all dates UTC)."""
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from .db import utcnow
from .models import AgentRun, Approval, Message, Post, Task

CONTEXT_LIMIT = 32000


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def search(session, company_id, user_id, query="", after=None, before=None, limit=20, max_run_id=None):
    """Dates are inclusive/exclusive. No caller-supplied tenant or user filters."""
    terms = re.findall(r"[\w-]{3,}", query)[:8]
    post_ref = re.search(r"(?:#|(?:пост|материал)\s*№?\s*)(\d+)\b", query, re.I)
    records = []
    sources = [
        (Message, Message.content, [Message.company_id == company_id, Message.user_id == user_id]
         if user_id is not None else [Message.id == -1]),
        (Post, Post.text, [Post.company_id == company_id]),
        (Task, Task.prompt, [Task.company_id == company_id]),
        (Approval, Approval.comment, [Approval.company_id == company_id]),
        (AgentRun, AgentRun.result, [AgentRun.company_id == company_id, AgentRun.kind == "scheduled"]),
    ]
    for model, text_col, filters in sources:
        if model is Message and max_run_id is not None:
            filters.append(or_(Message.run_id.is_(None), Message.run_id <= max_run_id))
        date_col = model.created_at if model is not Task else None
        if _date(after) and date_col is not None:
            filters.append(date_col >= _date(after))
        if _date(before) and date_col is not None:
            filters.append(date_col < _date(before))
        if post_ref:
            pid = int(post_ref.group(1))
            if model is Post:
                filters.append(Post.id == pid)
            elif model in (Message, Approval, AgentRun):
                filters.append(model.post_id == pid)
            else:
                continue
        elif terms:
            # SQLite's built-in lower() is ASCII-only. Include Cyrillic case variants.
            filters.append(or_(*(text_col.contains(v, autoescape=True) for t in terms
                                 for v in {t, t.lower(), t.capitalize(), t.upper()})))
        if model is Task and (after or before):
            continue  # legacy tasks have no creation date; do not invent one
        rows = (await session.execute(select(model).where(*filters).order_by(model.id.desc()).limit(limit))).scalars()
        for row in rows:
            record = {"source": model.__tablename__, "id": row.id,
                      "date_utc": getattr(row, "created_at", None).isoformat() if date_col is not None else None}
            if model is Message:
                record.update(role=row.role, text=row.content, run_id=row.run_id, post_id=row.post_id)
            elif model is Post:
                record.update(text=row.text, status=row.status, version=row.version, image_url=row.image_url)
            elif model is Task:
                record.update(prompt=row.prompt, active=row.active, interval_minutes=row.interval_minutes,
                              last_run_utc=row.last_run.isoformat() if row.last_run else None)
            elif model is AgentRun:
                record.update(prompt=row.prompt, text=row.result, status=row.status, post_id=row.post_id, task_id=row.task_id)
            else:
                record.update(post_id=row.post_id, version=row.post_version, decision=row.decision, comment=row.comment)
            records.append(record)
    return records


def bounded(records, limit=CONTEXT_LIMIT, text_limit=5000):
    selected, size = [], 0
    for record in records:
        item = dict(record)
        for key in ("text", "prompt", "comment"):
            if key in item:
                item[key] = str(item[key])[:text_limit]
        length = len(json.dumps(item, ensure_ascii=False))
        if size + length > limit:
            continue
        selected.append(item)
        size += length
    return json.dumps(selected, ensure_ascii=False)


async def context(session, company_id, user_id, text, parent_run_id=None, max_run_id=None):
    recent = await search(session, company_id, user_id, limit=12, max_run_id=max_run_id)
    related = []
    if parent_run_id:
        parent = await session.get(AgentRun, parent_run_id)
        if parent and parent.company_id == company_id and (
            parent.user_id == user_id or (parent.user_id is None and parent.task_id is not None)
        ):
            related.append({"source": "agent_runs", "id": parent.id, "date_utc": parent.created_at.isoformat(),
                            "prompt": parent.prompt, "text": parent.result, "post_id": parent.post_id})
            if parent.post_id:
                post = await session.get(Post, parent.post_id)
                if post and post.company_id == company_id:
                    related.insert(0, {"source": "posts", "id": post.id, "text": post.text,
                                       "status": post.status, "version": post.version, "image_url": post.image_url})
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if "вчера" in text.lower():
        found = await search(session, company_id, user_id, after=(day - timedelta(days=1)).isoformat(), before=day.isoformat(), max_run_id=max_run_id)
    else:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if dates and _date(dates[0]):
            found = await search(session, company_id, user_id, after=dates[0],
                                 before=(_date(dates[0]) + timedelta(days=1)).isoformat(), max_run_id=max_run_id)
        else:
            found = await search(session, company_id, user_id, query=text, max_run_id=max_run_id)
    # Reserve space for both the ongoing dialogue and historical matches.
    # A broad search must not crowd the latest personal turns out of the context.
    personal = [r for r in recent if r['source'] == 'messages']
    common = [r for r in recent if r['source'] != 'messages']
    sections = [(related, 8000, 5000), (personal, 10000, 1000), (found, 10000, 5000), (common, 4000, 2000)]
    selected, seen = [], set()
    for records, budget, text_limit in sections:
        for record in json.loads(bounded(records, budget, text_limit)):
            key = (record['source'], record['id'])
            if key not in seen:
                selected.append(record)
                seen.add(key)
    return bounded(selected)
