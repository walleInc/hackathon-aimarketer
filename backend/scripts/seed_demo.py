"""Создаёт тестовую компанию, подключает канал и печатает ссылку-приглашение.

Запуск:  python -m scripts.seed_demo @channel
"""
import asyncio
import secrets
import sys

from app.db import SessionLocal, init_db
from app.models import Company, Invite, KnowledgeDoc, SocialAccount


async def main(channel: str) -> None:
    await init_db()
    async with SessionLocal() as s:
        c = Company(
            name="Тестовая компания",
            description="Демонстрационная компания для проверки AI-маркетолога",
            brand_style="Дружелюбный, живой тон. Короткие абзацы. Без воды.",
        )
        s.add(c)
        await s.commit()
        s.add_all(
            [
                KnowledgeDoc(
                    company_id=c.id, title="О компании",
                    content="Кофейня «Зерно» открыта в 2021 году в Казани. Обжариваем кофе сами, "
                            "работаем ежедневно с 8:00 до 22:00. Адрес: ул. Баумана, 10.",
                ),
                KnowledgeDoc(
                    company_id=c.id, title="Продукты и аудитория",
                    content="Фирменный напиток — раф с лавандой. Есть безлактозное молоко и десерты без сахара. "
                            "Аудитория: студенты и молодые специалисты 18–35 лет.",
                ),
                SocialAccount(company_id=c.id, platform="telegram", channel_id=channel),
            ]
        )
        code = secrets.token_urlsafe(12)
        s.add(Invite(code=code, company_id=c.id, role="approver"))
        await s.commit()
        print(f"company_id={c.id}\ninvite=https://t.me/aimarketologgbot?start={code}")


asyncio.run(main(sys.argv[1]))
