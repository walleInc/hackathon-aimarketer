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

- `~/aimarketer/` — `docker-compose.yml` (из `docker-compose.prod.yml`), `.env` (секреты, только на сервере), `remote-deploy.sh`,
  `caddy/aimarketer.caddy`, `.current_tag`.
- Общий Caddy (`~/app`, контейнер `app-caddy-1`) выдаёт HTTPS-сертификаты и проксирует на `aimarketer-app:8000`
  по сети `aimarketer_net`; сайты подключаются сниппетами из `conf.d`.
- Приложение само ставит webhook Telegram на `PUBLIC_URL` при старте.

## Однократная подготовка

```bash
docker network create aimarketer_net
# ~/aimarketer/.env: BOT_TOKEN, ADMIN_IDS, PUBLIC_URL, WEBHOOK_SECRET, SECRET_KEY,
# POSTGRES_PASSWORD, LLM_PROVIDER, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, DEV_AUTH_BYPASS=false
```

Бренд-пакет (логотипы, шрифты клиента) в git не хранится. Загрузка и создание компании:

```bash
scp -r brand_pack deploy@<host>:aimarketer/brand_pack
cd ~/aimarketer && IMAGE_TAG=$(cat .current_tag) docker compose run --rm \
  -v "$PWD/brand_pack:/pack:ro" -e BRAND_PACK_DIR=/pack app python -m scripts.seed_brand @channel
```

## Откат и диагностика

```bash
cd ~/aimarketer
docker compose ps && docker compose logs --tail 100 app
cat .current_tag                      # текущая версия
```

Откат выполняется повторным запуском workflow на нужном коммите (Actions → Run workflow) либо `git revert`.
