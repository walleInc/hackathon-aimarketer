import type { ReactNode } from "react";

export const STATUS_RU: Record<string, string> = {
  draft: "Черновик", pending_approval: "На согласовании", approved: "Одобрен", rejected: "Отклонён",
  revision: "На доработке", publishing: "Публикуется", published: "Опубликован", failed: "Ошибка",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`chip ${status}`}>{STATUS_RU[status] ?? status}</span>;
}

export function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="kpi">
      <div className="kpiValue">{value}</div>
      <div className="kpiLabel">{label}</div>
      {hint && <div className="kpiHint">{hint}</div>}
    </div>
  );
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso + "Z").toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export const ACTION_RU: Record<string, string> = {
  "company.created": "Создана компания", "post.submitted": "Пост отправлен на согласование",
  "post.approve": "Пост одобрен", "post.reject": "Пост отклонён", "post.revise": "Запрошена доработка",
  "post.edited": "Текст поста изменён", "post.published": "Пост опубликован", "post.failed": "Ошибка публикации",
  "social.connected": "Подключён канал", "social.revoked": "Доступ к каналу отозван", "user.joined": "Сотрудник подключился",
  "task.created": "Создана задача", "task.run": "Задача выполнена", "task.toggled": "Задача включена/выключена",
  "invite.created": "Создано приглашение", "operator.added": "Добавлен оператор", "operator.removed": "Оператор удалён",
  "knowledge.deleted": "Удалён документ знаний", "knowledge.updated": "Обновлён документ знаний",
  "company.updated": "Изменены настройки компании", "brand.asset_added": "Добавлен файл бренд-кита",
  "brand.asset_deleted": "Удалён файл бренд-кита", "limit.tokens": "Исчерпан месячный бюджет AI",
};
