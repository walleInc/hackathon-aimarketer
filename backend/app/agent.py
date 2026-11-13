"""AI-маркетолог: понимает запрос, учитывает знания компании и историю, готовит материал по правилам бренда."""
import json
from dataclasses import dataclass

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import branding, cache, context_files, limits, platforms, services
from .config import settings
from .llm import get_llm
from .media import media_path
from .models import Company, KnowledgeDoc, Message, Post, UsageCost, User

KNOWLEDGE_LIMIT = 8000
HISTORY_LIMIT = 12

SYSTEM = """Ты — AI-маркетолог компании «{name}». Работаешь как SMM-менеджер и маркетолог.
Описание компании: {description}
Тон и стиль общения: {style}

ПРАВИЛА БРЕНДА (обязательны, нарушать нельзя):
{rules}

База знаний компании (используй только эти факты, ничего не выдумывай):
{knowledge}
"""

JSON_RULES = """
Отвечай СТРОГО JSON-объектом одного из видов:
{"action": "create_post", "platform": "telegram", "post_text": "...", "headline": "заголовок до 7 слов", "card_text": "одна короткая фраза до 140 символов для карточки", "image_prompt": "описание картинки", "reply": "что сообщить пользователю"}
{"action": "reply", "reply": "ответ пользователю"}
Выбирай create_post, когда просят подготовить публикацию/пост. На остальные вопросы отвечай reply,
опираясь на базу знаний и историю диалога. Пиши на языке пользователя."""

BRAND_CHECK = """ПРОВЕРКА_БРЕНДА
Проверь текст поста на соответствие правилам бренда, тону и фактам из базы знаний:
нет выдуманных фактов, название бренда написано верно, нет запрещённых формулировок.
Верни JSON: {{"ok": true|false, "issues": ["что не так"], "fixed_text": "исправленный текст, если ok=false"}}

Текст поста:
{text}"""


@dataclass
class AgentResult:
    reply: str
    post_id: int | None = None


async def _build_prompt(session: AsyncSession, company_id: int) -> str:
    company = await session.get(Company, company_id)
    docs = (
        await session.execute(select(KnowledgeDoc).where(KnowledgeDoc.company_id == company_id))
    ).scalars().all()
    knowledge = "\n\n".join(f"## {d.title}\n{d.content}" for d in docs)[:KNOWLEDGE_LIMIT]
    files = await context_files.load_context(company_id)  # файлы организации из Yandex S3: {organization_id}/{файл}
    if files:
        knowledge = f"{knowledge}\n\n{files}" if knowledge else files
    return SYSTEM.format(
        name=company.name, description=company.description or "—", style=company.brand_style or "—",
        rules=company.brand_rules or "—", knowledge=knowledge or "(пока пусто)",
    )


async def _system_prompt(session: AsyncSession, company_id: int, json_mode: bool = True) -> str:
    """Профиль бизнеса, база знаний и файлы организации — в кэше Redis; сбрасывается при любом изменении контекста."""
    prompt = await cache.cached(f"ctx:prompt:{company_id}", lambda: _build_prompt(session, company_id))
    return prompt + JSON_RULES if json_mode else prompt


async def _record_usage(session: AsyncSession, company_id: int, kind: str, tokens: int, cost: float) -> None:
    session.add(UsageCost(company_id=company_id, kind=kind, tokens=tokens, cost_usd=cost))
    await session.commit()


def llm_cost_usd(res) -> float:
    """Стоимость вызова: цена от провайдера, иначе по тарифу из настроек (вход и выход считаются по-разному)."""
    if res.cost_usd:
        return res.cost_usd
    return (
        res.prompt_tokens * settings.llm_price_input_per_m + res.completion_tokens * settings.llm_price_output_per_m
    ) / 1_000_000


async def _record_llm(session: AsyncSession, company_id: int, res) -> None:
    await _record_usage(session, company_id, "llm", res.tokens, llm_cost_usd(res))


def _strip_fences(text: str) -> str:
    """Некоторые модели оборачивают ответ в ```json ... ```."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _parse(text: str) -> dict:
    try:
        data = json.loads(_strip_fences(text))
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"action": "reply", "reply": text}


async def brand_check(session: AsyncSession, company: Company, text: str) -> tuple[str, str]:
    """Проверка материала перед отправкой на согласование. Возвращает (текст, заметки для согласующего)."""
    if not (company.brand_rules or company.brand_style):
        return text, ""
    res = await get_llm().complete(
        await _system_prompt(session, company.id, json_mode=False),
        [{"role": "user", "content": BRAND_CHECK.format(text=text)}],
        json_mode=True,
    )
    await _record_llm(session, company.id, res)
    data = _parse(res.text)
    if data.get("ok", True):
        return text, "Проверка бренда: замечаний нет"
    issues = "; ".join(str(i) for i in data.get("issues", [])) or "нарушены правила бренда"
    return (data.get("fixed_text") or text), f"Проверка бренда: исправлено автоматически ({issues})"


async def _make_image(session: AsyncSession, company: Company, data: dict, post_text: str) -> str:
    """Изображение для поста: ИИ-картинка с логотипом (если включена) или брендированная карточка."""
    brand = await branding.load_brand(session, company)
    if settings.ai_images and data.get("image_prompt"):
        url = await get_llm().generate_image(data["image_prompt"])
        if url and url.startswith("/media/") and media_path(url).exists():
            await _record_usage(session, company.id, "image", 0, 0.0)
            return branding.save_image(branding.place_logo(Image.open(media_path(url)), brand))
    headline = (data.get("headline") or post_text.split(".")[0])[:80]
    card_text = (data.get("card_text") or "")[:160]
    return branding.save_image(branding.render_card(brand, headline, card_text))


async def handle_message(session: AsyncSession, company_id: int, user: User | None, text: str) -> AgentResult:
    company = await session.get(Company, company_id)
    llm = get_llm()
    try:
        await limits.check_token_budget(session, company)
    except limits.LimitExceeded as e:
        if await limits.first_budget_alert(session, company_id):
            await services.audit(session, company_id, None, "limit.tokens", str(e))
            await services.notify_admins(f"Компания «{company.name}»: {e}")
        return AgentResult(reply=str(e))

    try:  # защита расходов на LLM: лимит запросов к AI на организацию и на пользователя
        await cache.rate_limit(f"ai:org:{company_id}", settings.ai_rate_limit_per_min)
        if user is not None:
            await cache.rate_limit(f"ai:user:{user.id}", settings.ai_rate_limit_per_user_per_min)
    except cache.RateLimited as e:
        return AgentResult(reply=str(e))

    session.add(Message(company_id=company_id, role="user", content=text))
    await session.commit()
    history = (
        await session.execute(
            select(Message).where(Message.company_id == company_id).order_by(Message.id.desc()).limit(HISTORY_LIMIT)
        )
    ).scalars().all()
    messages = [{"role": m.role, "content": m.content} for m in reversed(history)]

    res = await llm.complete(await _system_prompt(session, company_id), messages, json_mode=True)
    await _record_llm(session, company_id, res)
    data = _parse(res.text)

    post_id = None
    reply = data.get("reply") or ""
    if data.get("action") == "create_post" and data.get("post_text"):
        try:
            await limits.check_post_quota(session, company)
        except limits.LimitExceeded as e:
            reply = str(e)
        else:
            final_text, notes = await brand_check(session, company, data["post_text"])
            platform = data.get("platform") if data.get("platform") in platforms.REGISTRY else "telegram"
            post = Post(
                company_id=company_id, platform=platform, text=final_text, check_notes=notes,
                image_url=await _make_image(session, company, data, final_text),
                created_by=user.id if user else None,
            )
            session.add(post)
            await session.commit()
            await services.submit_for_approval(session, post)
            post_id = post.id

    reply = reply or "Готово."
    session.add(Message(company_id=company_id, role="assistant", content=reply))
    await session.commit()
    return AgentResult(reply=reply, post_id=post_id)


async def revise_post(session: AsyncSession, post: Post, comment: str, user_id: int | None = None) -> Post:
    """Переписывает текст по комментарию согласующего, проверяет бренд и снова отправляет на согласование."""
    company = await session.get(Company, post.company_id)
    await limits.check_token_budget(session, company)  # LimitExceeded обрабатывает вызывающий код
    prompt = (
        f"Перепиши пост по комментарию, сохрани факты и стиль бренда.\n\nПост:\n{post.text}\n\n"
        f"Комментарий: {comment}\n\nВерни только новый текст поста."
    )
    system = await _system_prompt(session, post.company_id, json_mode=False)
    res = await get_llm().complete(system, [{"role": "user", "content": prompt}])
    await _record_llm(session, post.company_id, res)
    text, notes = await brand_check(session, company, _strip_fences(res.text))
    post.check_notes = notes
    return await services.edit_post_text(session, post, text, user_id)
