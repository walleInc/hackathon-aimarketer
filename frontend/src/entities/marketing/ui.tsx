import { Badge, Card } from '@/shared/ui';
import type { ReactNode } from 'react';

export const STATUS_RU: Record<string, string> = {
  draft: 'Черновик',
  pending_approval: 'На согласовании',
  approved: 'Одобрен',
  rejected: 'Отклонён',
  revision: 'На доработке',
  publishing: 'Публикуется',
  published: 'Опубликован',
  failed: 'Ошибка',
};

export function StatusChip({ status }: { status: string }) {
  return (
    <Badge
      variant={
        status === 'failed' || status === 'rejected'
          ? 'destructive'
          : status === 'published'
            ? 'default'
            : 'secondary'
      }
    >
      {STATUS_RU[status] ?? status}
    </Badge>
  );
}

export function Kpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <Card className="kpi">
      <div className="kpiValue">{value}</div>
      <div className="kpiLabel">{label}</div>
      {hint && <div className="kpiHint">{hint}</div>}
    </Card>
  );
}

export function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(
    /Z$|[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z',
  ).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const ACTION_RU: Record<string, string> = {
  'company.created': 'Создана компания',
  'post.submitted': 'Пост отправлен на согласование',
  'post.approve': 'Пост одобрен',
  'post.reject': 'Пост отклонён',
  'post.revise': 'Запрошена доработка',
  'post.edited': 'Текст поста изменён',
  'post.published': 'Пост опубликован',
  'post.failed': 'Ошибка публикации',
  'social.connected': 'Подключён канал',
  'social.revoked': 'Доступ к каналу отозван',
  'user.joined': 'Сотрудник подключился',
  'task.created': 'Создана задача',
  'task.run': 'Задача выполнена',
  'task.deleted': 'Задача удалена',
  'post.rescheduled': 'Публикация перенесена',
  'telegram.connected': 'Подключена статистика Telegram',
  'telegram.disconnected': 'Отключена статистика Telegram',
  'task.toggled': 'Задача включена/выключена',
  'user.removed': 'Сотрудник удалён из компании',
  'user.role_changed': 'Изменена роль',
  'invite.created': 'Создано приглашение',
  'operator.added': 'Добавлен оператор',
  'operator.removed': 'Оператор удалён',
  'knowledge.deleted': 'Удалён документ знаний',
  'knowledge.updated': 'Обновлён документ знаний',
  'company.updated': 'Изменены настройки компании',
  'brand.asset_added': 'Добавлен файл бренд-кита',
  'brand.asset_deleted': 'Удалён файл бренд-кита',
  'limit.tokens': 'Исчерпан месячный бюджет AI',
};
