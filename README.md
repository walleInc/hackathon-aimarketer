# Автономный AI-маркетолог

Прототип для хакатона «Кибер 102»: Telegram-бот + Mini App + Core API с AI-агентом.

```
Telegram (бот, Mini App) ──► Core API (FastAPI)
                              ├─ auth: подпись initData, роли, изоляция по company_id
                              ├─ agent: LLM-провайдер (stub | openai | chatgpt_account)
                              ├─ workflow: автомат статусов согласования
                              ├─ scheduler: регулярные задачи и отложенная публикация
                              └─ platforms: telegram (vk, max — добавляются в REGISTRY)
```

## Запуск локально

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # заполните BOT_TOKEN, ADMIN_IDS
uvicorn app.main:app --reload
```

Без `PUBLIC_URL` бот работает через long polling. С `LLM_PROVIDER=stub` внешних вызовов нет —
можно проверить весь сценарий без ключей.

Mini App: `cd frontend && npm install && npm run dev` (для входа в браузере без Telegram
задайте `VITE_DEV_USER=<id>` и `DEV_AUTH_BYPASS=true` в backend/.env — только для разработки).
Для работы внутри Telegram нужен публичный HTTPS-адрес (cloudflared/ngrok или деплой) → `PUBLIC_URL`.

## Тесты

```bash
cd backend && .venv\Scripts\python -m pytest
```

Покрывают критерии: публикации нет без согласования, отклонённое не публикуется,
дублей нет, компании изолированы, токены не отдаются наружу.

## Подключение новой компании (без кода)

1. Откройте Mini App под администратором (ID в `ADMIN_IDS`) → «Компании» → «Создать».
2. Выберите компанию → добавьте знания (описание, продукты, аудитория).
3. «Канал для публикаций»: укажите `@channel`; бот должен быть админом канала.
4. «Приглашение» → отправьте ссылку согласующему; он переходит по ней и привязывается к компании.

## Деплой

`docker compose up -d --build` (Postgres + приложение; фронтенд собирается в образ и
отдаётся тем же сервисом). Задайте `PUBLIC_URL` — webhook ставится автоматически.

## Что не реализовано (честно)

- Подключение через аккаунт ChatGPT (`llm/chatgpt_account.py` — заготовка, критерий №12 требует проверки).
- Адаптеры VK и MAX, сбор статистики соцсетей, мониторинг комментариев, анализ конкурентов.
- Загрузка файлов/парсинг сайта в базу знаний (сейчас — текст через интерфейс).
- Миграции БД (Alembic): таблицы создаются при старте.
