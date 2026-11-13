import { type Stat } from '@/entities/marketing';

import { Card, Progress } from '@/shared/ui';

export function CompanyCard({ s, open }: { s: Stat; open: () => void }) {
  const ready = s.channels > 0 && s.users > 0;
  return (
    <Card
      className="card cursor-pointer transition hover:border-primary focus-visible:outline-2 focus-visible:outline-ring"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          open();
        }
      }}
      onClick={open}
    >
      <div className="cardHead">
        <b>{s.name}</b>
        <span
          className={`dot ${ready ? 'ok' : 'warn'}`}
          title={ready ? 'Готова к работе' : 'Нужна настройка'}
        />
      </div>
      <div className="stats">
        <span>
          <b>{s.posts.published ?? 0}</b> опубл.
        </span>
        <span>
          <b>{s.posts.pending_approval ?? 0}</b> ждут
        </span>
        <span>
          <b>{s.users}</b> в команде
        </span>
        <span>
          <b>{s.channels}</b> каналов
        </span>
      </div>
      <div className="budget" title="Токены за текущий месяц / месячный бюджет">
        <Progress
          aria-label="Месячный бюджет токенов"
          value={
            s.monthly_token_limit > 0
              ? Math.min(100, (s.month_tokens / s.monthly_token_limit) * 100)
              : 0
          }
          className={
            s.month_tokens >= s.monthly_token_limit
              ? '[&>div]:bg-destructive'
              : ''
          }
        />
        <small>
          {s.month_tokens.toLocaleString('ru-RU')} из{' '}
          {s.monthly_token_limit.toLocaleString('ru-RU')} токенов в месяц
          {s.cost_usd > 0 ? ` · $${s.cost_usd.toFixed(4)}` : ''}
        </small>
      </div>
      {!ready && (
        <div className="hint">
          {s.channels === 0 ? 'Не подключён канал' : 'Нет сотрудников'}
        </div>
      )}
    </Card>
  );
}
