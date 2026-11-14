"""Статистика публикаций и рекомендации с явными источниками и покрытием данных."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import utcnow
from .models import AnalyticsAdvice, MetricObservation, Post, PostMetrics

METRICS = ("views", "reactions", "forwards", "comments")
MAX_POSTS = 200


def iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


async def record_metrics(
    session: AsyncSession, post: Post, values: dict[str, int], observed_at: datetime,
    source: str = "manual", reject_stale: bool = True, update_id: int | None = None,
) -> None:
    if post.status != "published":
        raise ValueError("Статистика доступна только для опубликованных постов")
    if post.published_at and observed_at < post.published_at:
        raise ValueError("Измерение не может быть раньше публикации")
    if observed_at > utcnow() + timedelta(minutes=1):
        raise ValueError("Время измерения не может быть в будущем")
    if await session.get(PostMetrics, post.id) is None:
        try:
            async with session.begin_nested():
                session.add(PostMetrics(post_id=post.id, company_id=post.company_id))
                await session.flush()
        except IntegrityError:  # параллельное первое измерение
            pass
    accepted = {}
    for field, value in values.items():
        if field not in METRICS or isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_000_000_000:
            raise ValueError("Показатели должны быть целыми числами от 0 до 2 млрд")
        timestamp = getattr(PostMetrics, f"{field}_at")
        newer = or_(timestamp.is_(None), timestamp < observed_at)
        changes = {field: value, f"{field}_at": observed_at, f"{field}_source": source}
        if field == "reactions":
            changes["reactions_update_id"] = update_id if source == "telegram" else None
            if source == "telegram" and update_id is not None:
                # Telegram округляет время до секунд; update_id различает события в одной секунде.
                newer = or_(newer, and_(
                    timestamp == observed_at, PostMetrics.reactions_source == "telegram",
                    or_(PostMetrics.reactions_update_id.is_(None), PostMetrics.reactions_update_id < update_id),
                ))
        result = await session.execute(update(PostMetrics).where(
            PostMetrics.post_id == post.id, PostMetrics.company_id == post.company_id, newer,
        ).values(**changes),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1 and reject_stale:
            raise ValueError("Уже есть более свежее измерение. Обновите статистику и повторите")
        if result.rowcount == 1:
            accepted[field] = value
    if accepted:
        session.add(MetricObservation(company_id=post.company_id, post_id=post.id,
            values=json.dumps(accepted), observed_at=observed_at, source=source))


def post_row(post: Post, metrics: PostMetrics | None) -> dict:
    measurements = {
        field: {
            "value": getattr(metrics, field) if metrics else None,
            "observed_at": iso(getattr(metrics, f"{field}_at")) if metrics else None,
            "source": getattr(metrics, f"{field}_source") if metrics else "",
        }
        for field in METRICS
    }
    rate = None
    if metrics and metrics.views and metrics.reactions is not None and metrics.views_at and metrics.reactions_at:
        if abs((metrics.views_at - metrics.reactions_at).total_seconds()) <= 86400:
            rate = round(100 * metrics.reactions / metrics.views, 2)
    return {
        "id": post.id, "text": post.text, "platform": post.platform,
        "channel_id": post.published_channel_id, "external_id": post.external_id,
        "published_at": iso(post.published_at), "has_image": bool(post.image_url),
        "metrics": measurements, "reaction_rate": rate,
    }


def recommendations(rows: list[dict]) -> list[dict]:
    result = []
    if not rows:
        return [{"title": "Пока нет публикаций в выборке", "text": "Выберите другой период или опубликуйте пост, чтобы собрать показатели.", "post_ids": []}]
    covered = sum(row["metrics"]["views"]["value"] is not None for row in rows)
    if covered < len(rows):
        result.append({"title": "Дополните статистику просмотров", "text": f"Просмотры внесены для {covered} из {len(rows)} постов. Записывайте показатели через одинаковое время после публикации, например через 48 часов.", "post_ids": []})
    groups = defaultdict(list)
    for row in rows:
        # Без канала или времени публикации сравнение не имеет достаточного контекста.
        if row["channel_id"] and row["published_at"] and row["reaction_rate"] is not None and row["metrics"]["views"]["value"] >= 100:
            groups[(row["platform"], row["channel_id"])].append(row)
    for (_, channel), items in groups.items():
        if len(items) < 3:
            continue
        best = max(items, key=lambda row: row["reaction_rate"])
        typical = round(median(row["reaction_rate"] for row in items), 2)
        if best["reaction_rate"] > typical and best["reaction_rate"] > 0:
            result.append({
                "title": f"Проверьте подачу поста #{best['id']} ещё раз",
                "text": f"В канале {channel} у него {best['reaction_rate']}% реакций к просмотрам, медиана {len(items)} постов — {typical}%. Протестируйте похожую подачу на новой теме. Это гипотеза: возраст постов и момент измерения могут влиять на результат.",
                "post_ids": [best["id"]],
            })
    if not any(item["post_ids"] for item in result):
        result.append({"title": "Накопите сопоставимые измерения", "text": "Для сравнения нужны хотя бы три поста одного канала с известной датой публикации, минимум 100 просмотрами и измерениями просмотров и реакций с разницей не более суток. Пока оснований выделить удачную подачу недостаточно.", "post_ids": []})
    return result[:6]


async def dashboard(session: AsyncSession, company_id: int, days: int = 30) -> dict:
    filters = [Post.company_id == company_id, Post.status == "published"]
    if days:
        filters.append(Post.published_at >= utcnow() - timedelta(days=days))
    total = await session.scalar(select(func.count()).select_from(Post).where(*filters))
    unknown_dates = await session.scalar(select(func.count()).select_from(Post).where(
        Post.company_id == company_id, Post.status == "published", Post.published_at.is_(None),
    ))
    pairs = (await session.execute(select(Post, PostMetrics).outerjoin(
        PostMetrics, (PostMetrics.post_id == Post.id) & (PostMetrics.company_id == company_id),
    ).where(*filters).order_by(Post.published_at.desc(), Post.id.desc()).limit(MAX_POSTS))).all()
    rows = [post_row(post, metrics) for post, metrics in pairs]
    summary = {}
    for metric in METRICS:
        known = [row["metrics"][metric]["value"] for row in rows if row["metrics"][metric]["value"] is not None]
        summary[metric] = {"total": sum(known) if known else None, "measured_posts": len(known)}
    rate_rows = [row for row in rows if row["reaction_rate"] is not None]
    rate_views = sum(row["metrics"]["views"]["value"] for row in rate_rows)
    summary["reaction_rate"] = round(100 * sum(row["metrics"]["reactions"]["value"] for row in rate_rows) / rate_views, 2) if rate_views else None
    summary["rate_posts"] = len(rate_rows)
    trend = defaultdict(int)
    for row in rows:
        if row["published_at"]:
            day = (datetime.fromisoformat(row["published_at"]) + timedelta(hours=3)).date().isoformat()
            trend[day] += 1
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    report = (await session.execute(select(AnalyticsAdvice).where(
        AnalyticsAdvice.company_id == company_id, AnalyticsAdvice.period_days == days,
    ).order_by(AnalyticsAdvice.id.desc()).limit(1))).scalar_one_or_none()
    return {
        "period_days": days, "published_posts": total, "sample_size": len(rows), "max_posts": MAX_POSTS,
        "unknown_publication_dates": unknown_dates, "summary": summary, "posts": rows,
        "daily_publications": [{"date": day, "posts": count} for day, count in sorted(trend.items())],
        "recommendations": recommendations(rows), "data_hash": fingerprint,
        "ai_advice": {"text": report.text, "created_at": iso(report.created_at), "stale": report.data_hash != fingerprint} if report else None,
    }
