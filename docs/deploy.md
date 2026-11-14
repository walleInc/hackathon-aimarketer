# Деплой

Каждый коммит в `main` запускает GitHub Actions (`.github/workflows/deploy.yml`):

1. **test** — `pytest` (backend) и сборка фронтенда.
2. **deploy** — сборка Docker-образа, доставка на сервер (`docker save | ssh | docker load`), запуск
   `deploy/remote-deploy.sh`, проверка `https://194-226-125-175.sslip.io/health`.

Образ собирается в CI, потому что на сервере 1 ГБ RAM. Новая версия поднимается и проверяется healthcheck-ом;
**только после успеха удаляются все прошлые версии**. Если новая версия не стартовала — возвращается предыдущая.
Данные (Postgres, media) хранятся в томах `aimarketer_pgdata` и `aimarketer_media` и деплоем не затрагиваются.

## Секреты GitHub (Settings → Secrets and variables → Actions)

| Секрет | Значение |
|---|---|
| `DEPLOY_HOST` | IP сервера |
| `DEPLOY_USER` | пользователь для деплоя |
| `DEPLOY_SSH_KEY` | приватный ключ, выделенный только для CI |
| `DEPLOY_KNOWN_HOSTS` | строка(и) из `ssh-keyscan -t ed25519 <host>` — защита от подмены сервера |

## Устройство на сервере

- `~/aimarketer/` — `docker-compose.yml` (из `docker-compose.prod.yml`), `.env.temp` (секреты, только на сервере), `remote-deploy.sh`,
  `caddy/aimarketer.caddy`, `.current_tag`.
- Общий Caddy (`~/app`, контейнер `app-caddy-1`) выдаёт HTTPS-сертификаты и проксирует на `aimarketer-app:8000`
  по сети `aimarketer_net`; сайты подключаются сниппетами из `conf.d`.
- Приложение само ставит webhook Telegram на `PUBLIC_URL` при старте.

## Однократная подготовка

```bash
docker network create aimarketer_net
# ~/aimarketer/.env.temp: BOT_TOKEN, ADMIN_IDS, PUBLIC_URL, WEBHOOK_SECRET, SECRET_KEY,
# POSTGRES_PASSWORD, LLM_PROVIDER, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, DEV_AUTH_BYPASS=false
```

При переходе с `.env` скопируйте его в `.env.temp` и сохраните прежний `POSTGRES_PASSWORD`:

```bash
cd ~/aimarketer
cp -n .env .env.temp
chmod 600 .env.temp
```

`env_file` передаёт настройки приложению, а `--env-file .env.temp` задаёт значения для подстановки в Compose (включая пароль Postgres).

Бренд-пакет (логотипы, шрифты клиента) в git не хранится. Загрузка и создание компании:

```bash
scp -r brand_pack deploy@<host>:aimarketer/brand_pack
cd ~/aimarketer && IMAGE_TAG=$(cat .current_tag) docker compose --env-file .env.temp run --rm \
  -v "$PWD/brand_pack:/pack:ro" -e BRAND_PACK_DIR=/pack app python -m scripts.seed_brand @channel
```

## Откат и диагностика

```bash
cd ~/aimarketer
docker compose --env-file .env.temp ps && docker compose --env-file .env.temp logs --tail 100 app
cat .current_tag                      # текущая версия
```

Откат выполняется повторным запуском workflow на нужном коммите (Actions → Run workflow) либо `git revert`.

## Задачи по расписанию: внешние источники

В серверном `.env.temp` (локально — `backend/.env`) задайте:

```dotenv
TAVILY_API_KEY=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
```

`TAVILY_API_KEY` используется только задачами анализа рынка. Для работы реального ИИ нужен настроенный
`LLM_PROVIDER`; `stub` предназначен для разработки. Telegram API credentials получают на
[my.telegram.org](https://my.telegram.org). Подключение бота и пользовательского аккаунта независимы:
администратор компании открывает miniapp → «Задачи», вводит номер, код Telegram и при необходимости
пароль 2FA, затем выбирает канал своего аккаунта. Сессия хранится в БД зашифрованной; код и пароль не сохраняются.
Каналы, добавленные через этот экран, предназначены для аналитики и не становятся адресатами публикаций.
Отключение аккаунта отзывает сессию в Telegram. Сохраняйте прежний `SECRET_KEY` между деплоями.

Полная статистика зависит от прав аккаунта и доступности статистики канала в Telegram. Если она недоступна,
сервис собирает доступные счётчики постов и явно указывает ограничения. Без подключения внешних источников
подготовка постов и рекомендации продолжают работать; задания рынка/статистики показывают причину ошибки.

При старте автоматически добавляются поля расписаний, история запусков и уникальный индекс связи поста с запуском.
Существующие задачи сохраняют прежний интервал. Перед обновлением сохраните резервную копию БД.
Повторная доставка задания безопасна; ожидающие запуски восстанавливаются из БД, зависшие — по истечении аренды
15 минут. После трёх неудачных попыток ошибка остаётся в истории, отправляется уведомление оператору.

Проверки разработчика:

```bash
cd backend && pytest -q
cd ../frontend && npm ci && npm run build
npx playwright install chromium
npm run test:e2e
```

Для назначенных публикаций допускается обычная задержка очереди: максимум 60 секунд
(или два интервала планировщика, если это больше). Более старые посты после простоя автоматически
не публикуются: в miniapp потребуется выбрать новое время.

## Контент-планы

Новых ключей не требуется: генерация использует существующий `LLM_PROVIDER` и бюджет компании.
В production нужны действующие воркеры очереди `ai-generation` и тик планировщика. Без Redis генерация
выполняется после отправки HTTP-ответа в том же процессе; необработанные дни подхватит планировщик.
При старте создаются три таблицы контент-планов и добавляются nullable-поля связи и снимка задания в `posts`.
Существующие публикации и API аналитики/референсов сохраняются.

Для дополнительной проверки на отдельной PostgreSQL базе:

```bash
cd backend
CONTENT_PLAN_TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost/testdb pytest tests/test_content_plans_postgres.py -q
```

Тест создаёт случайную временную схему, проверяет повторную миграцию старой таблицы публикаций,
генерацию плана и создание поста, затем удаляет только свою схему.
