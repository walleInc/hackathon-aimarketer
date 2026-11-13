import io
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import branding, limits, services
from ..auth import Ctx, require_admin
from ..config import settings
from ..db import get_session, utcnow
from ..media import media_path, new_media_file
from ..models import BrandAsset, AuditLog, Company, Invite, KnowledgeDoc, Post, SocialAccount, Task, UsageCost, User
from ..security import encrypt

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


async def _company(session: AsyncSession, company_id: int) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "Компания не найдена")
    return company


class CompanyCreate(BaseModel):
    name: str
    description: str = ""
    brand_style: str = ""
    brand_rules: str = ""
    brand_colors: str = ""
    daily_post_limit: int = 5
    monthly_token_limit: int = 300000


class CompanyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    brand_style: str | None = None
    brand_rules: str | None = None
    brand_colors: str | None = None
    daily_post_limit: int | None = None
    monthly_token_limit: int | None = None


def company_out(c: Company) -> dict:
    return {
        "id": c.id, "name": c.name, "description": c.description, "brand_style": c.brand_style,
        "brand_rules": c.brand_rules, "brand_colors": c.brand_colors,
        "daily_post_limit": c.daily_post_limit, "monthly_token_limit": c.monthly_token_limit,
    }


@router.get("/companies")
async def list_companies(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Company).order_by(Company.id))).scalars()
    return [company_out(c) for c in rows]


@router.post("/companies")
async def create_company(body: CompanyCreate, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    company = Company(**body.model_dump())
    session.add(company)
    await session.commit()
    await services.audit(session, company.id, ctx.user.id, "company.created", company.name)
    return {"id": company.id}


@router.put("/companies/{company_id}")
async def update_company(company_id: int, body: CompanyUpdate, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    company = await _company(session, company_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in changes.items():
        setattr(company, k, v)
    await session.commit()
    await services.audit(session, company_id, ctx.user.id, "company.updated", ", ".join(changes))
    return {"ok": True}


class KnowledgeIn(BaseModel):
    title: str
    content: str


@router.put("/knowledge/{doc_id}")
async def update_knowledge(doc_id: int, body: KnowledgeIn, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    doc = await session.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise HTTPException(404)
    doc.title, doc.content, doc.updated_at = body.title, body.content, utcnow()
    await session.commit()
    await services.audit(session, doc.company_id, ctx.user.id, "knowledge.updated", doc.title)
    return {"ok": True}


ALLOWED_EXT = {
    "logo_color": {".png"}, "logo_white": {".png"}, "logo_black": {".png"}, "icon": {".png"},
    "pattern": {".png", ".jpg", ".jpeg", ".webp"}, "example": {".png", ".jpg", ".jpeg", ".webp"},
    "font_heading": {".ttf", ".otf"}, "font_body": {".ttf", ".otf"},
}
MAX_UPLOAD = 15 * 1024 * 1024


@router.get("/companies/{company_id}/assets")
async def list_assets(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(BrandAsset).where(BrandAsset.company_id == company_id).order_by(BrandAsset.id))).scalars()
    return [{"id": a.id, "kind": a.kind, "filename": a.filename, "url": a.path} for a in rows]


@router.post("/companies/{company_id}/assets")
async def upload_asset(
    company_id: int, kind: str = Form(...), file: UploadFile = File(...),
    ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session),
):
    await _company(session, company_id)
    if kind not in ALLOWED_EXT:
        raise HTTPException(422, f"Неизвестный тип файла: {kind}")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT[kind]:
        raise HTTPException(422, f"Для «{kind}» допустимы: {', '.join(sorted(ALLOWED_EXT[kind]))}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Файл больше 15 МБ")
    if kind not in ("font_heading", "font_body"):
        try:  # убеждаемся, что это действительно изображение
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            raise HTTPException(422, "Файл не является изображением")
    path, url = new_media_file(f"brand/{company_id}", ext)
    path.write_bytes(data)
    asset = BrandAsset(company_id=company_id, kind=kind, filename=file.filename or path.name, path=url)
    session.add(asset)
    await session.commit()
    await services.audit(session, company_id, ctx.user.id, "brand.asset_added", f"{kind}: {asset.filename}")
    return {"id": asset.id, "url": url}


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    asset = await session.get(BrandAsset, asset_id)
    if asset is None:
        raise HTTPException(404)
    media_path(asset.path).unlink(missing_ok=True)
    await session.delete(asset)
    await session.commit()
    await services.audit(session, asset.company_id, ctx.user.id, "brand.asset_deleted", asset.filename)
    return {"ok": True}


class PreviewIn(BaseModel):
    headline: str = "Заголовок публикации"
    body: str = "Короткий поясняющий текст карточки."
    style: str = "dark"


@router.post("/companies/{company_id}/brand/preview")
async def brand_preview(company_id: int, body: PreviewIn, session: AsyncSession = Depends(get_session)):
    """Пробная карточка в фирменном стиле компании — чтобы проверить бренд-кит до публикаций."""
    company = await _company(session, company_id)
    brand = await branding.load_brand(session, company)
    img = branding.render_card(brand, body.headline, body.body, "light" if body.style == "light" else "dark")
    return {"url": branding.save_image(img, "previews")}


class InviteIn(BaseModel):
    role: str = "approver"  # approver | member


@router.post("/companies/{company_id}/invite")
async def create_invite(company_id: int, body: InviteIn, session: AsyncSession = Depends(get_session)):
    await _company(session, company_id)
    if body.role not in ("approver", "member"):
        raise HTTPException(422, "role must be approver|member")
    code = secrets.token_urlsafe(12)
    session.add(Invite(code=code, company_id=company_id, role=body.role))
    await session.commit()
    return {"code": code, "start_param": code, "deeplink_hint": f"https://t.me/<bot_username>?start={code}"}


@router.get("/companies/{company_id}/knowledge")
async def list_knowledge(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(KnowledgeDoc).where(KnowledgeDoc.company_id == company_id))).scalars()
    return [
        {"id": d.id, "title": d.title, "content": d.content, "size": len(d.content), "updated_at": d.updated_at}
        for d in rows
    ]


@router.post("/companies/{company_id}/knowledge")
async def add_knowledge(company_id: int, body: KnowledgeIn, session: AsyncSession = Depends(get_session)):
    await _company(session, company_id)
    doc = KnowledgeDoc(company_id=company_id, title=body.title, content=body.content)
    session.add(doc)
    await session.commit()
    return {"id": doc.id}


class SocialIn(BaseModel):
    platform: str = "telegram"
    channel_id: str
    token: str = ""  # пусто = использовать токен основного бота


@router.post("/companies/{company_id}/social")
async def add_social(company_id: int, body: SocialIn, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await _company(session, company_id)
    acc = SocialAccount(
        company_id=company_id, platform=body.platform, channel_id=body.channel_id, token_encrypted=encrypt(body.token)
    )
    session.add(acc)
    await session.commit()
    await services.audit(session, company_id, ctx.user.id, "social.connected", f"{body.platform}:{body.channel_id}")
    return {"id": acc.id}


@router.get("/companies/{company_id}/social")
async def list_social(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(SocialAccount).where(SocialAccount.company_id == company_id))).scalars()
    # токены наружу не отдаются никогда
    return [{"id": a.id, "platform": a.platform, "channel_id": a.channel_id, "active": a.active} for a in rows]


@router.delete("/social/{account_id}")
async def revoke_social(account_id: int, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    acc = await session.get(SocialAccount, account_id)
    if acc is None:
        raise HTTPException(404)
    acc.active, acc.token_encrypted = False, ""
    await session.commit()
    await services.audit(session, acc.company_id, ctx.user.id, "social.revoked", str(acc.id))
    return {"ok": True}


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    """Сводка для дашборда: по каждой компании — посты по статусам, команда, расходы."""
    companies = (await session.execute(select(Company).order_by(Company.id))).scalars().all()
    posts = await session.execute(select(Post.company_id, Post.status, func.count()).group_by(Post.company_id, Post.status))
    by_company: dict[int, dict[str, int]] = {}
    for cid, status, n in posts:
        by_company.setdefault(cid, {})[status] = n
    users = dict((await session.execute(select(User.company_id, func.count()).group_by(User.company_id))).all())
    channels = dict(
        (await session.execute(
            select(SocialAccount.company_id, func.count()).where(SocialAccount.active.is_(True)).group_by(SocialAccount.company_id)
        )).all()
    )
    usage = (await session.execute(
        select(UsageCost.company_id, func.sum(UsageCost.tokens), func.sum(UsageCost.cost_usd)).group_by(UsageCost.company_id)
    )).all()
    tokens = {cid: t for cid, t, _ in usage}
    costs = {cid: c for cid, _, c in usage}
    month_tokens = {c.id: await limits.tokens_this_month(session, c.id) for c in companies}
    return [
        {
            "id": c.id, "name": c.name, "posts": by_company.get(c.id, {}), "users": users.get(c.id, 0),
            "channels": channels.get(c.id, 0), "tokens": int(tokens.get(c.id) or 0),
            "cost_usd": round(float(costs.get(c.id) or 0), 4),
            "month_tokens": month_tokens[c.id], "monthly_token_limit": c.monthly_token_limit,
        }
        for c in companies
    ]


@router.get("/companies/{company_id}/users")
async def company_users(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).where(User.company_id == company_id))).scalars()
    return [{"id": u.id, "telegram_id": u.telegram_id, "name": u.name, "role": u.role} for u in rows]


@router.get("/companies/{company_id}/posts")
async def company_posts(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Post).where(Post.company_id == company_id).order_by(Post.id.desc()).limit(50))).scalars()
    return [
        {"id": p.id, "platform": p.platform, "text": p.text, "status": p.status, "version": p.version,
         "error": p.error, "created_at": p.created_at, "image_url": p.image_url, "check_notes": p.check_notes}
        for p in rows
    ]


@router.get("/companies/{company_id}/tasks")
async def company_tasks(company_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Task).where(Task.company_id == company_id))).scalars()
    return [
        {"id": t.id, "prompt": t.prompt, "interval_minutes": t.interval_minutes, "active": t.active, "last_run": t.last_run}
        for t in rows
    ]


class TaskToggle(BaseModel):
    active: bool


@router.patch("/tasks/{task_id}")
async def toggle_task(task_id: int, body: TaskToggle, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(404)
    task.active = body.active
    await session.commit()
    await services.audit(session, task.company_id, ctx.user.id, "task.toggled", f"task={task.id} active={body.active}")
    return {"ok": True}


@router.delete("/knowledge/{doc_id}")
async def delete_knowledge(doc_id: int, ctx: Ctx = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    doc = await session.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise HTTPException(404)
    await session.delete(doc)
    await session.commit()
    await services.audit(session, doc.company_id, ctx.user.id, "knowledge.deleted", doc.title)
    return {"ok": True}


@router.get("/audit")
async def audit_log(company_id: int | None = None, session: AsyncSession = Depends(get_session)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(200)
    if company_id:
        q = q.where(AuditLog.company_id == company_id)
    return [
        {"id": a.id, "company_id": a.company_id, "user_id": a.user_id, "action": a.action,
         "details": a.details, "created_at": a.created_at}
        for a in (await session.execute(q)).scalars()
    ]


@router.get("/usage")
async def usage(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(UsageCost.company_id, UsageCost.kind, func.sum(UsageCost.tokens), func.sum(UsageCost.cost_usd))
        .group_by(UsageCost.company_id, UsageCost.kind)
    )
    return [{"company_id": c, "kind": k, "tokens": t or 0, "cost_usd": float(s or 0)} for c, k, t, s in rows]
