"""Модели БД. Каждая клиентская таблица содержит company_id — это основа изоляции данных."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Float, UniqueConstraint, Index, Date
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


class ContentPlan(Base):
    __tablename__ = "content_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    posts_per_day: Mapped[int] = mapped_column(Integer)
    wishes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContentPlanDay(Base):
    __tablename__ = "content_plan_days"
    __table_args__ = (UniqueConstraint("plan_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plans.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str] = mapped_column(String(40), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")


class ContentPlanItem(Base):
    __tablename__ = "content_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plans.id"), index=True)
    planned_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


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
    content_plan_item_id: Mapped[int | None] = mapped_column(ForeignKey("content_plan_items.id"), nullable=True, index=True)
    content_plan_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
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
