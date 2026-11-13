import { useState } from 'react';
import { api, ACTION_RU, Kpi, fmtDate } from "@/entities/marketing";
import { useLoad } from '@/shared/lib';
import { Button, Card } from '@/shared/ui';

import { NewCompany } from '@/widgets/new-company';
import { CompanyCard } from '@/widgets/company-card';
export function Dashboard({ open }: { open: (id: number) => void }) {
  const [stats, reload, error] = useLoad(() => api.stats(), []);
  const [audit] = useLoad(() => api.audit(), []);
  const [creating, setCreating] = useState(false);

  const sum = (key: string) =>
    (stats ?? []).reduce((a, s) => a + (s.posts[key] ?? 0), 0);
  const tokens = (stats ?? []).reduce((a, s) => a + s.tokens, 0);
  const cost = (stats ?? []).reduce((a, s) => a + s.cost_usd, 0);

  return (
    <>
      {error && <Card className="card error">{error}</Card>}
      <div className="kpis">
        <Kpi label="Компаний" value={stats?.length ?? '—'} />
        <Kpi label="Опубликовано" value={sum('published')} />
        <Kpi
          label="Ждут согласования"
          value={sum('pending_approval')}
          hint={sum('failed') ? `${sum('failed')} с ошибкой` : undefined}
        />
        <Kpi
          label="Токенов LLM"
          value={tokens.toLocaleString('ru-RU')}
          hint={
            cost > 0
              ? `≈ $${cost.toFixed(4)} по тарифу модели`
              : 'стоимость не задана (LLM_PRICE_*)'
          }
        />
      </div>

      <div className="sectionHead">
        <h2>Компании</h2>
        <Button
          type="button"
          variant="default"
          onClick={() => setCreating(!creating)}
        >
          {creating ? 'Отмена' : '+ Новая компания'}
        </Button>
      </div>
      {creating && (
        <NewCompany
          done={(id) => {
            setCreating(false);
            reload();
            open(id);
          }}
        />
      )}

      <div className="companyGrid">
        {(stats ?? []).map((s) => (
          <CompanyCard key={s.id} s={s} open={() => open(s.id)} />
        ))}
        {stats?.length === 0 && (
          <Card className="card muted">
            Пока нет компаний. Создайте первую.
          </Card>
        )}
      </div>

      <div className="sectionHead">
        <h2>Последние действия</h2>
      </div>
      <Card className="card">
        {(audit ?? []).slice(0, 8).map((a) => (
          <div className="logRow" key={a.id}>
            <span className="muted">{fmtDate(a.created_at)}</span>
            <span>{ACTION_RU[a.action] ?? a.action}</span>
            <span className="muted">{a.details}</span>
          </div>
        ))}
        {audit?.length === 0 && <span className="muted">Журнал пуст.</span>}
      </Card>
    </>
  );
}
