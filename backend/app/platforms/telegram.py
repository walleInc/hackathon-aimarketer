from aiogram import Bot
from aiogram.types import FSInputFile

from .base import PublishResult
from ..config import settings
from ..media import media_path
from ..models import SocialAccount
from ..security import decrypt

CAPTION_LIMIT = 1024


class TelegramPlatform:
    async def publish(self, account: SocialAccount, text: str, image_url: str = "") -> PublishResult:
        token = decrypt(account.token_encrypted) or settings.bot_token
        if not token:
            raise RuntimeError("Не задан токен бота для публикации")
        bot = Bot(token)
        try:
            if image_url:
                photo = FSInputFile(media_path(image_url)) if image_url.startswith("/media/") else image_url
                if len(text) <= CAPTION_LIMIT:
                    msg = await bot.send_photo(account.channel_id, photo, caption=text)
                else:  # длинный текст не помещается в подпись — отправляем отдельно
                    await bot.send_photo(account.channel_id, photo)
                    msg = await bot.send_message(account.channel_id, text)
            else:
                msg = await bot.send_message(account.channel_id, text)
            return PublishResult(external_id=str(msg.message_id), channel_id=str(msg.chat.id))
        finally:
            await bot.session.close()
