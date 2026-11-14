"""Telegram-бот: свободный текст → агент, согласование inline-кнопками, уведомления."""
import io
import logging
import secrets

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)
from sqlalchemy import select

from . import agent, cache, limits, post_images, services
from .config import settings
from .db import SessionLocal
from .media import media_path
from .models import Company, Invite, Post, User
from .workflow import InvalidTransition

log = logging.getLogger(__name__)

bot: Bot | None = Bot(settings.bot_token) if settings.bot_token else None
dp = Dispatcher()


def _webapp_markup() -> InlineKeyboardMarkup | None:
    if not settings.public_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть кабинет", web_app=WebAppInfo(url=settings.public_url))]]
    )


async def _get_user(session, tg_id: int) -> User | None:
    user = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
    if user is None and tg_id in settings.admin_id_set:
        user = User(telegram_id=tg_id, role="admin")
        session.add(user)
        await session.commit()
    return user


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    code = (message.text or "").partition(" ")[2].strip()
    async with SessionLocal() as session:
        if code:
            invite = (
                await session.execute(select(Invite).where(Invite.code == code, Invite.used.is_(False)))
            ).scalar_one_or_none()
            if invite is None:
                await message.answer("Приглашение недействительно или уже использовано.")
                return
            user = await _get_user(session, message.from_user.id)
            if user is not None and user.role == "admin":
                await message.answer(
                    "Это технический аккаунт поставщика услуги: он создаёт компании и не создаёт материалы. "
                    "Для работы в компании используйте другой аккаунт Telegram.",
                    reply_markup=_webapp_markup(),
                )
                return
            if user is None:
                user = User(telegram_id=message.from_user.id)
                session.add(user)
            user.company_id = invite.company_id
            user.role = invite.role
            user.name = message.from_user.full_name
            invite.used = True
            await session.commit()
            await services.audit(session, invite.company_id, user.id, "user.joined", f"role={invite.role}")
            await message.answer(
                "Готово! Вы подключены. Напишите задачу обычным текстом, например: "
                "«Подготовь пост про нашу новую услугу»." + _ROLE_HELP[invite.role],
                reply_markup=_webapp_markup() if invite.role == "approver" else None,
            )
            return
        user = await _get_user(session, message.from_user.id)
    if user is None:
        await message.answer("Для доступа нужна ссылка-приглашение от вашего менеджера.")
    elif user.role == "admin":
        await message.answer("Технический аккаунт поставщика услуги. Компании настраиваются в кабинете.", reply_markup=_webapp_markup())
    else:
        await message.answer(
            "Я AI-маркетолог. Напишите задачу обычным текстом." + _ROLE_HELP.get(user.role, ""),
            reply_markup=_webapp_markup() if user.role == "approver" else None,
        )


_ROLE_HELP = {
    "approver": "\n\nВы администратор компании: материалы приходят вам на согласование, знания, бренд и каналы "
                "настраиваются в кабинете (кнопка ниже). Команда /invite — ссылка для нового сотрудника.",
    "member": "\n\nГотовые материалы уйдут на согласование администратору компании, о решении я сообщу.",
}


@dp.message(Command("invite"))
async def on_invite(message: Message) -> None:
    """Администратор компании приглашает сотрудников без обращения к оператору."""
    async with SessionLocal() as session:
        user = await _get_user(session, message.from_user.id)
        if user is None or user.role != "approver" or user.company_id is None:
            await message.answer("Приглашать сотрудников может администратор компании.")
            return
        code = secrets.token_urlsafe(8)
        session.add(Invite(code=code, company_id=user.company_id, role="member"))
        await session.commit()
        await services.audit(session, user.company_id, user.id, "invite.created", "member via bot")
    me = await message.bot.me()
    await message.answer(f"Ссылка для сотрудника (одноразовая):\nhttps://t.me/{me.username}?start={code}")


def _approval_kb(post_id: int, version: int) -> InlineKeyboardMarkup:
    def btn(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=f"post:{post_id}:{version}:{action}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("✅ Одобрить", "approve"), btn("❌ Отклонить", "reject")],
            [btn("✏️ Доработать", "revise"), btn("📝 Изменить текст", "edit_text")],
            [btn("🎨 Перегенерировать картинку", "regenerate")],
            [btn("📎 Загрузить свою картинку", "upload_image")],
        ]
    )


async def notify_approval(post_id: int) -> None:
    """Отправляет согласующим материал: текст, площадку и время публикации."""
    if bot is None:
        return
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        approvers = (
            await session.execute(
                select(User).where(User.company_id == post.company_id, User.role == "approver")
            )
        ).scalars().all()
    if not approvers:  # без администратора компании согласовать некому — сообщаем поставщику услуги
        await notify_admins(f"В компании {post.company_id} нет администратора, материал #{post.id} ждёт согласования.")
        return
    when = post.scheduled_at.strftime("%d.%m.%Y %H:%M UTC") if post.scheduled_at else "сразу после одобрения"
    notes = f"\n\n🔎 {post.check_notes}" if post.check_notes else ""
    text = f"📝 Материал на согласование (#{post.id}, версия {post.version})\nПлощадка: {post.platform}\nПубликация: {when}\n\n{post.text}{notes}"
    for user in approvers:
        try:
            if post.image_url:
                photo = FSInputFile(media_path(post.image_url)) if post.image_url.startswith("/media/") else post.image_url
                await bot.send_photo(user.telegram_id, photo)
            await bot.send_message(user.telegram_id, text[:4000], reply_markup=_approval_kb(post.id, post.version))
        except Exception:
            log.exception("cannot notify user %s", user.telegram_id)


async def notify_user(telegram_id: int, text: str) -> None:
    if bot is None:
        return
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        log.exception("cannot notify user %s", telegram_id)


async def notify_admins(text: str) -> None:
    if bot is None:
        return
    async with SessionLocal() as session:  # операторы из ADMIN_IDS и добавленные через админку
        db_ids = set((await session.execute(select(User.telegram_id).where(User.role == "admin"))).scalars())
    for admin_id in settings.admin_id_set | db_ids:
        try:
            await bot.send_message(admin_id, f"⚠️ {text}")
        except Exception:
            log.exception("cannot notify admin %s", admin_id)


@dp.callback_query(F.data.startswith("post:"))
async def on_decision(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) != 4:
        await cb.answer("Это старое уведомление. Откройте актуальный материал в кабинете", show_alert=True)
        return
    _, post_id_s, version_s, action = parts
    if not post_id_s.isdigit() or not version_s.isdigit():
        await cb.answer("Некорректная кнопка", show_alert=True)
        return
    async with SessionLocal() as session:
        user = await _get_user(session, cb.from_user.id)
        if user is None or user.company_id is None:
            await cb.answer("Нет доступа", show_alert=True)
            return
        if user.role != "approver":
            await cb.answer("Согласовывать может только администратор компании", show_alert=True)
            return
        # изоляция: пост ищется только в компании пользователя
        post = await session.get(Post, int(post_id_s))
        if post is None or post.company_id != user.company_id:
            await cb.answer("Пост не найден", show_alert=True)
            return
        if post.version != int(version_s):
            await cb.answer("Версия устарела. Используйте новое уведомление или кабинет", show_alert=True)
            return
        try:
            if action in ("edit_text", "regenerate", "upload_image"):
                services.require_editable(post)
                await cache.set_state(user.id, f"{action}:{post.id}:{post.version}")
                instruction = {
                    "edit_text": "Пришлите полный новый текст поста одним сообщением.",
                    "regenerate": "Опишите новую картинку. Генерация оплачивается по тарифу провайдера.",
                    "upload_image": "Пришлите фото или файл PNG, JPEG, WebP размером до 10 МБ.",
                }[action]
                await cb.message.answer(f"Пост #{post.id}. {instruction} Для отмены: /cancel")
            elif action == "revise":
                try:  # бюджет проверяем до смены статуса, чтобы пост не застрял «на доработке»
                    await limits.check_token_budget(session, await session.get(Company, post.company_id))
                except limits.LimitExceeded as e:
                    await cb.answer(str(e), show_alert=True)
                    return
                await services.decide(session, post, user, "revise", version=int(version_s))
                await cache.set_state(user.id, f"revise:{post.id}:{post.version}")  # временное состояние диалога — в Redis с TTL
                await cb.message.answer(f"Что изменить в посте #{post.id}? Ответьте одним сообщением.")
            else:
                post = await services.decide(session, post, user, action, version=int(version_s))
                label = {"approved": "✅ Одобрено", "rejected": "❌ Отклонено"}.get(post.status)
                if post.status == "published":
                    label = "✅ Одобрено и опубликовано"
                elif post.status == "failed":
                    label = f"⚠️ Одобрено, но публикация не удалась: {post.error}"
                await cb.message.answer(f"{label or post.status} (пост #{post.id})")
        except InvalidTransition as e:
            await cb.answer(str(e), show_alert=True)
            return
    await cb.answer()


@dp.message(Command("cancel"))
async def cancel_edit(message: Message) -> None:
    async with SessionLocal() as session:
        user = await _get_user(session, message.from_user.id)
        if user:
            await cache.clear_state(user.id)
    await message.answer("Действие отменено.")


@dp.message(F.photo | F.document)
async def on_post_image(message: Message) -> None:
    async with SessionLocal() as session:
        user = await _get_user(session, message.from_user.id)
        if not user or user.role != "approver" or user.company_id is None:
            await message.answer("Менять изображение может только администратор компании.")
            return
        state = await cache.get_state(user.id)
        if not state.startswith("upload_image:"):
            await message.answer("Сначала нажмите «Загрузить свою картинку» у нужного поста.")
            return
        _, pid, version = state.split(":")
        file = message.photo[-1] if message.photo else message.document
        if file.file_size and file.file_size > post_images.MAX_IMAGE_BYTES:
            await message.answer("Изображение должно быть не больше 10 МБ.")
            return
        url = None
        try:
            post = await services.get_post(session, user.company_id, int(pid))
            services.require_editable(post)
            if post.version != int(version):
                raise InvalidTransition("Версия устарела. Выберите актуальный материал")
            downloaded = io.BytesIO()
            await message.bot.download(file, destination=downloaded)
            url = post_images.save_upload(downloaded.getvalue())
            await services.edit_post_image(session, post, url, user.id, int(version))
        except (services.NotFound, InvalidTransition, ValueError) as e:
            if url:
                media_path(url).unlink(missing_ok=True)
            await message.answer(str(e))
            return
        await cache.clear_state(user.id)
        await message.answer("Картинка заменена. Материал отправлен на повторное согласование.")


@dp.message(F.text)
async def on_text(message: Message) -> None:
    async with SessionLocal() as session:
        user = await _get_user(session, message.from_user.id)
        if user is None:
            await message.answer("Для доступа нужна ссылка-приглашение от вашего менеджера.")
            return
        if user.role != "admin" and user.company_id is None:
            await message.answer("У вас нет доступа к компании. Нужна новая ссылка-приглашение от администратора.")
            return
        if user.role == "admin":
            await message.answer(
                "Это технический аккаунт: компании настраиваются в кабинете. Материалы создают сотрудники компаний.",
                reply_markup=_webapp_markup(),
            )
            return
        state = await cache.get_state(user.id)
        if state.startswith(("edit_text:", "regenerate:", "upload_image:")):
            if user.role != "approver":
                await cache.clear_state(user.id)
                await message.answer("Менять материал может только администратор компании.")
                return
            action, pid, version = state.split(":")
            if action == "upload_image":
                await message.answer("Пришлите изображение или /cancel для отмены.")
                return
            try:
                post = await services.get_post(session, user.company_id, int(pid))
                if action == "edit_text":
                    post.check_notes = "Текст изменён вручную; требуется проверка согласующего"
                    await services.edit_post_text(session, post, message.text, user.id, int(version))
                else:
                    await message.answer("Генерирую новую картинку…")
                    await agent.regenerate_post_image(session, post, message.text, user.id, int(version))
            except (services.NotFound, InvalidTransition, ValueError, limits.LimitExceeded, cache.RateLimited, cache.LockBusy) as e:
                await message.answer(str(e) if not isinstance(e, cache.LockBusy) else "Картинка уже генерируется")
                return
            await cache.clear_state(user.id)
            await message.answer("Обновил материал и отправил на повторное согласование.")
            return
        if state.startswith("revise:"):  # комментарий к доработке
            post_id = int(state.split(":")[1])
            await cache.clear_state(user.id)
            post = await session.get(Post, post_id)
            if post and post.company_id == user.company_id:
                if user.role != "approver" or (len(state.split(":")) == 3 and post.version != int(state.split(":")[2])):
                    await message.answer("Нет доступа или версия устарела. Откройте актуальный материал.")
                    return
                try:
                    services.require_editable(post)
                    await agent.revise_post(session, post, message.text, user.id)
                except (limits.LimitExceeded, InvalidTransition) as e:
                    await cache.set_state(user.id, state)  # можно повторить комментарий позже
                    await message.answer(str(e))
                    return
                await message.answer("Доработал и отправил на повторное согласование.")
                return
        await message.bot.send_chat_action(message.chat.id, "typing")
        result = await agent.handle_message(session, user.company_id, user, message.text)
        await message.answer(result.reply)
