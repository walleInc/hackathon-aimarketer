#!/usr/bin/env bash
# Запускается на сервере из CI: bash ~/aimarketer/remote-deploy.sh <тег образа>
# Новая версия поднимается рядом со старой; прошлые версии удаляются только после успешного healthcheck.
# При провале возвращается предыдущая версия, а новый образ удаляется.
set -euo pipefail

TAG="${1:?usage: remote-deploy.sh <image-tag>}"
cd "$HOME/aimarketer"

PREV="$(cat .current_tag 2>/dev/null || true)"
docker image inspect "aimarketer:$TAG" >/dev/null

export IMAGE_TAG="$TAG"
if ! docker compose up -d --remove-orphans --wait --wait-timeout 150; then
  echo "::error::Версия $TAG не прошла healthcheck, откат на '${PREV:-нет предыдущей}'"
  docker compose logs --tail 60 app || true
  if [ -n "$PREV" ] && docker image inspect "aimarketer:$PREV" >/dev/null 2>&1; then
    IMAGE_TAG="$PREV" docker compose up -d --wait --wait-timeout 150 || true
  fi
  docker rmi "aimarketer:$TAG" >/dev/null 2>&1 || true
  exit 1
fi
echo "$TAG" > .current_tag

# удаляем все прошлые версии приложения и осиротевшие слои
docker images aimarketer --format '{{.Tag}}' | grep -vx "$TAG" | xargs -r -I{} docker rmi "aimarketer:{}" || true
docker image prune -f >/dev/null

# общий Caddy подхватывает сниппет сайта (идемпотентно)
docker exec app-caddy-1 caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
  || echo "::warning::caddy reload не удался, проверьте конфигурацию"

echo "Развёрнуто: $TAG (предыдущая: ${PREV:-нет})"
docker images aimarketer --format 'образ: {{.Repository}}:{{.Tag}} {{.Size}}'
df -h / | tail -1
