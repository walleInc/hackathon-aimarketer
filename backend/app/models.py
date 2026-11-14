"""Модели БД. Каждая клиентская таблица содержит company_id — это основа изоляции данных."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Float, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    brand_style: Mapped[str] = mapped_column(Text, default="")  # тон и стиль общения
    brand_rules: Mapped[str] = mapped_column(Text, default="")  # правила бренда: что можно и нельзя
    brand_colors: Mapped[str] = mapped_column(Text, default="")  # HEX через запятую, основной цвет первый
    daily_post_limit: Mapped[int] = mapped_column(Integer, default=5)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=300000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BrandAsset(Base):
    """Файлы бренд-кита: логотипы, паттерны, шрифты, примеры."""

    __tablename__ = "brand_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    # logo_color | logo_white | logo_black | icon | pattern | font_heading | font_body | example
    kind: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(500))  # URL вида /media/brand/<company>/<file>
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # admin — оператор сервиса; approver — согласует публикации; member — ставит задачи
    role: Mapped[str] = mapped_column(String(20), default="member")
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(100), default="")  # например "revise:12"


class Invite(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    role: Mapped[str] = mapped_column(String(20), default="approver")
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))  # telegram | vk | max
    channel_id: Mapped[str] = mapped_column(String(200))
    analytics_only: Mapped[bool] = mapped_column(Boolean, default=False)
    token_encrypted: Mapped[str] = mapped_column(Text, default="")  # пусто = токен основного бота
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)


class Task(Base):
    """Регулярная задача по расписанию: агент сам готовит материал и отправляет на согласование."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kind: Mapped[str] = mapped_column(String(30), default="post")
    schedule_kind: Mapped[str] = mapped_column(String(20), default="legacy")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    local_time: Mapped[str] = mapped_column(String(5), default="09:00")
    weekdays: Mapped[str] = mapped_column(String(30), default="")
    next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "scheduled_for"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str] = mapped_column(String(40), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[str] = mapped_column(Text, default="[]")
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TelegramConnection(Base):
    __tablename__ = "telegram_connections"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    session_encrypted: Mapped[str] = mapped_column(Text, default="")
    pending_encrypted: Mapped[str] = mapped_column(Text, default="")
    auth_owner: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="message")
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    expected_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RunDelivery(Base):
    """Durable notification outbox. One recipient per run; resume at the next unsent chunk."""
    __tablename__ = "run_deliveries"
    __table_args__ = (UniqueConstraint("run_id", "telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    next_chunk: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (Index("uq_posts_task_run_id", "task_run_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), default="telegram")
    text: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    needs_reschedule: Mapped[bool] = mapped_column(Boolean, default=False)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str] = mapped_column(String(200), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_channel_id: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    check_notes: Mapped[str] = mapped_column(Text, default="")  # результат проверки на соответствие бренду
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    post_version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20))  # approve | reject | revise
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsageCost(Base):
    __tablename__ = "usage_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40))  # llm | image
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PostMetrics(Base):
    """Последние известные показатели; отсутствие измерения отличается от нуля."""
    __tablename__ = "post_metrics"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    views_source: Mapped[str] = mapped_column(String(20), default="")
    reactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reactions_source: Mapped[str] = mapped_column(String(20), default="")
    reactions_update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forwards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwards_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forwards_source: Mapped[str] = mapped_column(String(20), default="")
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comments_source: Mapped[str] = mapped_column(String(20), default="")


class AnalyticsAdvice(Base):
    __tablename__ = "analytics_advice"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    period_days: Mapped[int] = mapped_column(Integer)
    data_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketingSettings(Base):
    __tablename__ = "marketing_settings"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    niche: Mapped[str] = mapped_column(String(500), default="")
    geography: Mapped[str] = mapped_column(String(300), default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    report_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str] = mapped_column(String(1000), default="")
    telegram: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketingDocument(Base):
    """Versioned structured research/report; a run can save only one result."""
    __tablename__ = "marketing_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id"), unique=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    data: Mapped[str] = mapped_column(Text)
    sources: Mapped[str] = mapped_column(Text, default="[]")
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketingHypothesis(Base):
    __tablename__ = "marketing_hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("marketing_documents.id"))
    title: Mapped[str] = mapped_column(String(300))
    evidence: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(300))
    success: Mapped[str] = mapped_column(Text)
    duration_days: Mapped[int] = mapped_column(Integer, default=14)
    status: Mapped[str] = mapped_column(String(40), default="proposed")
    result: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContentPlanItem(Base):
    __tablename__ = "content_plan_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("marketing_documents.id"))
    topic: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(100))
    rubric: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str] = mapped_column(Text)
    day: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SocialMetricSnapshot(Base):
    """Telegram counters at a point in time; includes posts created outside this app."""
    __tablename__ = "social_metric_snapshots"
    __table_args__ = (UniqueConstraint("company_id", "channel_id", "external_id", "observed_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    channel_id: Mapped[str] = mapped_column(String(200), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(30), default="text")
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    values: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(30))
