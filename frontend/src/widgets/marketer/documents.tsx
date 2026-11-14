import { Badge, Card } from '@/shared/ui';
import { fmtDate, type MarketingDocument } from '@/entities/marketing';

export function SourceLink({ url, children }: { url: string; children: React.ReactNode }) {
  return /^https?:\/\//i.test(url) ? <a className="marketing-link" href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}
export function DocumentView({ item }: { item: MarketingDocument }) {
  const d = item.data;
  const totals = item.metrics.totals as Record<string, { value: number | null; measured: number }> | undefined;
  return <Card className="card marketing-document">
    <div className="cardHead"><Badge variant="secondary">Версия #{item.id}</Badge><span className="muted">{fmtDate(item.created_at)}</span></div>
    <p className="marketing-summary">{d.summary}</p>
    {d.findings?.map((f, i) => <div className="marketing-finding" key={i}><h4>{f.title}</h4><p>{f.detail}</p>
      {f.source_urls?.map((url, j) => <SourceLink key={j} url={url}>Источник {j + 1} ↗</SourceLink>)}
    </div>)}
    {d.positioning && <div className="marketing-finding"><h4>Позиционирование</h4><p>{d.positioning}</p></div>}
    {([['goals', 'Цели'], ['audiences', 'Аудитории'], ['channels', 'Каналы'], ['rubrics', 'Рубрики'], ['kpis', 'Целевые KPI']] as const).map(([key, label]) =>
      !!d[key]?.length && <div className="marketing-finding" key={key}><h4>{label}</h4><ul>{d[key]!.map((v, i) => <li key={i}>{v}</li>)}</ul></div>)}
    {!!d.actions?.length && <div className="marketing-actions"><h4>Рекомендуемые действия</h4><ol>{d.actions.map((a, i) => <li key={i}>{a}</li>)}</ol></div>}
    {!!d.limitations?.length && <div className="note"><b>Ограничения анализа</b><ul>{d.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></div>}
    {!!item.sources.length && <details className="marketing-sources"><summary>Источники · {item.sources.length}</summary><ul>{item.sources.map((s, i) => <li key={i}><SourceLink url={s.url}>{s.title || s.url}</SourceLink></li>)}</ul></details>}
    {item.kind === 'report' && <details><summary>Зафиксированные показатели отчёта</summary>
      <p className="muted">Публикации за {String(item.metrics.days ?? '—')} дней до формирования отчёта. Канал: {String(item.metrics.channel || 'все')}. Счётчики на момент измерений.</p>
      <dl className="marketing-dl">{([['views', 'Просмотры'], ['reactions', 'Реакции'], ['forwards', 'Пересылки'], ['comments', 'Комментарии']] as const).map(([key, label]) => <div key={key} className="contents"><dt>{label}</dt><dd>{totals?.[key]?.value == null ? 'Нет данных' : totals[key].value!.toLocaleString('ru-RU')} · измерено {totals?.[key]?.measured ?? 0} постов</dd></div>)}<dt>Заявки и продажи</dt><dd>Нет данных — источник не подключён</dd></dl>
    </details>}
  </Card>;
}
