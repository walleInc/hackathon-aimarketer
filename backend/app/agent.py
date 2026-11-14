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
from .models import Company, KnowledgeDoc, Message, Post, Task, UsageCost, User

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
{"action": "schedule_task", "task_prompt": "что готовить регулярно", "interval_minutes": 1440, "reply": "что сообщить пользователю"}
{"action": "reply", "reply": "ответ пользователю"}

Ты не чат-бот для бесед, а исполнитель: твоя работа — готовить публикации.
- create_post: ЛЮБОЙ запрос, где нужен материал для соцсетей — пост, текст, анонс, акция, новость, идея, объявление,
  «напиши», «подготовь», «придумай», «сделай» про продукт, услугу, событие или тему. Не обсуждай — сразу готовь
  готовый текст в post_text. Если данных мало, используй то, что есть в базе знаний, и не выдумывай факты.
- schedule_task: просят делать что-то регулярно («каждый день», «раз в неделю»). interval_minutes — период в минутах.
- reply: ТОЛЬКО вопросы о компании, истории и ранее принятых решениях, либо если для поста нет ни одного факта
  (тогда попроси нужные сведения).
Пиши на языке пользователя."""

_CONTENT_HINTS = (
    "пост", "напиши", "подготов", "придума", "анонс", "публикац", "объявлен", "акци", "текст для", "сделай", "создай",
    "рассылк", "новост", "контент", "сторис", "заголов",
)


def _looks_like_post_request(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in _CONTENT_HINTS)


FORCE_POST = (
    "Пользователь просит готовый материал. Ответь ТОЛЬКО JSON вида create_post "
    "(platform, post_text, headline, card_text, image_prompt, reply) без пояснений. "
    "post_text — готовый текст публикации, а не обсуждение."
)

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


async def _make_image(session: AsyncSession, company: Company, data: dict, post_text: str, reference: bytes | None = None) -> str:
    """Изображение для поста: ИИ-картинка с логотипом (если включена) или брендированная карточка."""
    brand = await branding.load_brand(session, company)
    if reference is not None or (settings.ai_images and data.get("image_prompt")):
        prompt = data.get("image_prompt") or post_text
        llm = get_llm()
        if reference is not None:
            url = await llm.generate_image(prompt, reference=reference)
        else:
            url = await llm.generate_image(prompt)
        if url and url.startswith("/media/") and media_path(url).exists():
            await _record_usage(session, company.id, "image", 0, 0.0)
            return branding.save_image(branding.place_logo(Image.open(media_path(url)), brand))
    if reference is not None:
        raise ValueError("Не удалось создать изображение по референсу. Попробуйте ещё раз.")
    headline = (data.get("headline") or post_text.split(".")[0])[:80]
    card_text = (data.get("card_text") or "")[:160]
    return branding.save_image(branding.render_card(brand, headline, card_text))


async def handle_message(session: AsyncSession, company_id: int, user: User | None, text: str, reference: bytes | None = None) -> AgentResult:
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
    # История подаётся в том же JSON-формате, что и требуемый ответ: иначе модель копирует прежние
    # ответы обычным текстом и перестаёт выполнять действия.
    messages = [
        {"role": m.role, "content": json.dumps({"action": "reply", "reply": m.content}, ensure_ascii=False)
         if m.role == "assistant" else m.content}
        for m in reversed(history)
    ]

    if reference is not None:
        messages[-1]["content"] += (
            "\nК запросу приложено изображение-референс для генератора картинки. "
            "Создай пост и image_prompt с инструкциями по использованию референса; "
            "не утверждай, что видишь содержимое изображения."
        )
    res = await llm.complete(await _system_prompt(session, company_id), messages, json_mode=True)
    await _record_llm(session, company_id, res)
    data = _parse(res.text)

    # Модель ответила беседой на просьбу о материале — один раз повторяем с жёстким требованием выдать пост.
    if _looks_like_post_request(text) and not (
        (data.get("action") == "create_post" and data.get("post_text")) or data.get("action") == "schedule_task"
    ):
        forced = await llm.complete(
            await _system_prompt(session, company_id),
            [{"role": "user", "content": f"{text}\n\n{FORCE_POST}"}],  # без истории: прежние ответы-беседы сбивают модель
            json_mode=True,
        )
        await _record_llm(session, company_id, forced)
        retry = _parse(forced.text)
        if retry.get("action") == "create_post" and retry.get("post_text"):
            data = retry

    post_id = None
    reply = data.get("reply") or ""
    if data.get("action") == "schedule_task" and data.get("task_prompt"):
        interval = max(int(data.get("interval_minutes") or 1440), 60)
        task = Task(company_id=company_id, prompt=str(data["task_prompt"])[:1000], interval_minutes=interval)
        session.add(task)
        await session.commit()
        await services.audit(session, company_id, user.id if user else None, "task.created", f"task={task.id} via chat")
        reply = reply or f"Готово, буду готовить материалы по расписанию: раз в {interval // 60 or 1} ч."
    elif data.get("action") == "create_post" and data.get("post_text"):
        try:
            await limits.check_post_quota(session, company)
        except limits.LimitExceeded as e:
            reply = str(e)
        else:
            final_text, notes = await brand_check(session, company, data["post_text"])
            platform = data.get("platform") if data.get("platform") in platforms.REGISTRY else "telegram"
            post = Post(
                company_id=company_id, platform=platform, text=final_text, check_notes=notes,
                image_url=await _make_image(session, company, data, final_text, reference=reference),
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


async def regenerate_post_image(
    session: AsyncSession, post: Post, prompt: str, user_id: int, version: int | None = None,
) -> Post:
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Описание картинки должно содержать от 1 до 4000 символов")
    services.require_editable(post)
    expected = post.version if version is None else version
    if expected != post.version:
        raise services.InvalidTransition("Материал уже изменён. Обновите его перед генерацией")
    if not settings.ai_images:
        raise ValueError("Генерация изображений отключена. Включите AI_IMAGES в настройках сервера")
    company = await session.get(Company, post.company_id)
    await limits.check_token_budget(session, company)
    await cache.rate_limit(f"ai:org:{company.id}", settings.ai_rate_limit_per_min)
    await cache.rate_limit(f"ai:user:{user_id}", settings.ai_rate_limit_per_user_per_min)
    async with cache.lock(f"image-generation:{post.id}", ttl_sec=600):
        description = (
            f"Создай изображение для публикации компании «{company.name}».\n"
            f"Правила бренда: {company.brand_rules}\nФирменные цвета: {company.brand_colors}\n"
            f"Контекст публикации:\n{post.text}\n\nЗадание на изображение:\n{prompt}\n"
            "Не выдумывай характеристики, цифры и сертификаты. Не рисуй логотип: он будет добавлен отдельно."
        )
        url = await get_llm().generate_image(description)
        if not url or not url.startswith("/media/") or not media_path(url).is_file():
            raise ValueError("Не удалось сгенерировать изображение. Прежняя картинка сохранена")
        await _record_usage(session, company.id, "image", 0, 0.0)
        brand = await branding.load_brand(session, company)
        with Image.open(media_path(url)) as image:
            final_url = branding.save_image(branding.place_logo(image, brand))
        try:
            return await services.edit_post_image(session, post, final_url, user_id, expected)
        except services.InvalidTransition:
            media_path(final_url).unlink(missing_ok=True)
            raise
