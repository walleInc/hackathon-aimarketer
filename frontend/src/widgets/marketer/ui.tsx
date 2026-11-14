import { useEffect, useState } from 'react';
import { Activity, ArrowUpRight, BarChart3, BookOpen, CheckCircle2, Compass, FileText, FlaskConical, RefreshCw, Target, Users } from 'lucide-react';
import { api, workspaceApi, fmtDate, type Hypothesis, type HypothesisStatus, type MarketingKind, type MarketingState } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';
import { Badge, Button, Card, ConfirmAction, Input, Label, Textarea } from '@/shared/ui';
import { CompetitorForm, ProfileForm } from './forms';
import { DocumentView, SourceLink } from './documents';

const screens = [
  { id: 'overview', label: 'Обзор', icon: Activity }, { id: 'research', label: 'Рынок', icon: Compass },
  { id: 'competitors', label: 'Конкуренты', icon: Users }, { id: 'content', label: 'Контент и аналитика', icon: BarChart3 },
  { id: 'hypotheses', label: 'Гипотезы', icon: FlaskConical }, { id: 'strategy', label: 'Стратегия и план', icon: Target },
  { id: 'report', label: 'Отчёты', icon: FileText },
] as const;
type Screen = (typeof screens)[number]['id'];
const kindNames: Record<string, string> = { research: 'Исследование рынка', competitors: 'Анализ конкурентов', hypotheses: 'Гипотезы', strategy: 'Стратегия', plan: 'Контент-план', report: 'Отчёт', sync: 'Сбор Telegram', post: 'Подготовка поста' };
const statuses: Record<string, string> = { pending: 'В очереди', running: 'Выполняется', succeeded: 'Готово', failed: 'Ошибка', cancelled: 'Отменено', skipped: 'Пропущено' };
const hypothesisStatuses: Record<HypothesisStatus, string> = { proposed: 'Предложена', running: 'В работе', confirmed: 'Подтверждена', rejected: 'Не подтверждена', insufficient: 'Недостаточно данных', archived: 'Архив' };
const formatNames: Record<string, string> = { text: 'Текст', photo: 'Фото', video: 'Видео' };
const metrics = [{ key: 'views', label: 'Просмотры' }, { key: 'reactions', label: 'Реакции' }, { key: 'forwards', label: 'Пересылки' }, { key: 'comments', label: 'Комментарии' }] as const;
const number = (v: number | null) => v === null ? '—' : v.toLocaleString('ru-RU');
type Act = (fn: () => Promise<unknown>, success?: string) => Promise<void>;

function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return <Card className="card marketing-empty"><BookOpen size={28} strokeWidth={1.3} /><h3>{title}</h3><p className="muted">{children}</p></Card>;
}
function HypothesisCard({ item, busy, writable, act, id }: { item: Hypothesis; busy: boolean; writable: boolean; act: Act; id: number }) {
  const [status, setStatus] = useState(item.status);
  const [result, setResult] = useState(item.result);
  return <Card className="card space-y-3"><div className="cardHead"><Badge variant="secondary">{hypothesisStatuses[item.status]}</Badge><span className="muted">{item.duration_days} дней</span></div>
    <h3>{item.title}</h3><dl className="marketing-dl"><dt>Основание</dt><dd>{item.evidence}</dd><dt>Эксперимент</dt><dd>{item.action}</dd><dt>Метрика</dt><dd>{item.metric}</dd><dt>Критерий успеха</dt><dd>{item.success}</dd></dl>
    {writable ? <fieldset disabled={busy}><Label>Статус гипотезы<select className="task-select" value={status} onChange={(e) => setStatus(e.target.value as HypothesisStatus)}>{Object.entries(hypothesisStatuses).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></Label>
      <Label>Результат эксперимента<Textarea value={result} onChange={(e) => setResult(e.target.value)} maxLength={4000} placeholder="Фактические значения и вывод; при нехватке данных укажите это" /></Label>
      <div className="row"><Button variant="outline" onClick={() => void act(() => workspaceApi.hypothesis(id, item.id, status, result), 'Гипотеза обновлена')}>Сохранить результат</Button>
        <Button disabled={!!item.task_id} onClick={() => void act(() => workspaceApi.prepare(id, 'hypotheses', item.id), 'Пост отправлен в подготовку. После генерации он поступит на согласование.')}>{item.task_id ? 'Пост передан в подготовку' : 'Подготовить пост'}</Button></div>
    </fieldset> : item.result && <p>{item.result}</p>}
  </Card>;
}
function ReportSchedule({ state, id, busy, act }: { state: MarketingState; id: number; busy: boolean; act: Act }) {
  const s = state.schedule;
  const [active, setActive] = useState(s?.active ?? true);
  const [zone, setZone] = useState(s?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC');
  const [time, setTime] = useState(s?.local_time ?? '09:00');
  return <Card className="card"><h3>Регулярный отчёт</h3><p className="muted">По понедельникам. Показатели за публикации последних 7 дней; уведомление администраторам компании в Telegram.</p>
    <p className="note">{s?.active ? `Включён · ${s.timezone} · следующий запуск ${fmtDate(s.next_run)}` : 'Автоматическая отправка выключена'}</p>
    {state.permissions.manage && <form onSubmit={(e) => { e.preventDefault(); void act(() => workspaceApi.schedule(id, active, zone, time), 'Расписание отчётов сохранено'); }}><fieldset disabled={busy}>
      <Label className="marketing-checkbox"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Включить еженедельный отчёт</Label>
      <div className="row2"><Label>Часовой пояс отчётов<Input value={zone} required maxLength={80} onChange={(e) => setZone(e.target.value)} /></Label><Label>Время отчёта<Input type="time" value={time} required onChange={(e) => setTime(e.target.value)} /></Label></div>
      <Button type="submit" variant="outline">Сохранить расписание</Button></fieldset></form>}
  </Card>;
}

export function Marketer({ id }: { id: number }) {
  const [screen, setScreen] = useState<Screen>('overview');
  const [days, setDays] = useState(30);
  const [channel, setChannel] = useState('');
  const [state, reload, loadError] = useLoad(() => workspaceApi.state(id, days, channel), [id, days, channel]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [prompt, setPrompt] = useState('');
  const [syncChannel, setSyncChannel] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);
  const [shownPosts, setShownPosts] = useState(20);
  useEffect(() => { setShownPosts(20); }, [days, channel]);
  const pending = state?.runs.some((r) => r.status === 'pending' || r.status === 'running');
  useEffect(() => { if (!pending) return; const timer = window.setInterval(reload, 5000); return () => clearInterval(timer); }, [pending, reload]);
  const act: Act = async (fn, success = 'Сохранено') => {
    setBusy(true); setError(''); setMessage('');
    try { await fn(); setMessage(success); reload(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Не удалось выполнить действие'); throw e; }
    finally { setBusy(false); }
  };
  // Event handlers consume rejected operations; forms retain their data on error.
  const action: Act = async (fn, success) => { try { await act(fn, success); } catch { /* rendered above */ } };
  const start = (kind: MarketingKind) => action(() => workspaceApi.start(id, kind, days, channel, prompt), 'Задача принята. Результат появится в этом разделе.');
  const canWrite = !!state?.permissions.write;
  const docs = state?.documents.filter((d) => d.kind === screen) ?? [];
  const renderDocuments = (kind: MarketingKind) => {
    const all = state?.documents.filter((d) => d.kind === kind) ?? [];
    if (!all.length) return <Empty title="Анализ ещё не сформирован">Настройте контекст компании и запустите анализ. Результат и источники сохранятся здесь.</Empty>;
    return <><DocumentView item={all[0]} />{all.length > 1 && <details className="marketing-history"><summary>Предыдущие версии · {all.length - 1}</summary>{all.slice(1).map((d) => <DocumentView key={d.id} item={d} />)}</details>}</>;
  };
  return <section className="marketing-workspace" aria-label="Кабинет маркетолога">
    <div className="marketing-hero"><div><p className="marketing-eyebrow">Исследования → решения → результат</p><h2>Кабинет маркетолога</h2><p>Понимать рынок. Проверять идеи. Измерять результат.</p></div><div className="marketing-hero-mark"><Compass size={52} strokeWidth={1} /></div></div>
    {loadError && <div role="alert" className="error marketing-feedback">{loadError}<Button variant="outline" onClick={reload}>Повторить загрузку</Button></div>}
    {!state && !loadError && <p role="status">Загружаем кабинет маркетолога…</p>}
    {state && <>
      {state.sources.demo && <p className="note">Демонстрационный AI-провайдер. Счётчики показывают сохранённые данные; тексты AI требуют подключения рабочей модели.</p>}
      <div className="marketing-layout"><nav className="marketing-nav" aria-label="Разделы маркетолога">{screens.map(({ id: key, label, icon: Icon }) => <button type="button" key={key} aria-current={screen === key ? 'page' : undefined} onClick={() => { setScreen(key); setError(''); setMessage(''); }}><Icon size={18} /><span>{label}</span>{screen === key && <ArrowUpRight size={14} />}</button>)}</nav>
        <div className="marketing-main">
          <div className="marketing-toolbar"><div><p className="marketing-eyebrow">Рабочее пространство</p><h3>{screens.find((s) => s.id === screen)?.label}</h3></div>
            <div className="row"><Label>Период<select className="task-select" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 дней</option><option value={30}>30 дней</option><option value={90}>90 дней</option></select></Label>
              <Label>Канал<select className="task-select" value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">Все каналы</option>{Array.from(new Set([...state.channels.map((c) => c.channel_id), ...state.analytics.posts.map((p) => p.channel)])).filter(Boolean).map((c) => <option key={c} value={c}>{c}</option>)}</select></Label>
              <Button variant="outline" size="icon" title="Обновить кабинет" aria-label="Обновить кабинет" onClick={reload}><RefreshCw size={17} /></Button></div>
          </div>
          {error && <p role="alert" className="error marketing-feedback">{error}</p>}{message && <p role="status" className="marketing-feedback marketing-success"><CheckCircle2 size={18} />{message}</p>}
          {pending && <p role="status" className="note">Анализ выполняется. Можно перейти в другой раздел — результаты сохранятся.</p>}
          {state.runs.some((r) => r.status === 'failed') && <details className="marketing-run-errors"><summary>Есть ошибки запусков</summary>{state.runs.filter((r) => r.status === 'failed').map((r) => <p key={r.id} className="error">#{r.id} · {kindNames[r.kind]}: {r.error}</p>)}</details>}

          {screen === 'overview' && <>
            <div className="marketing-kpis">{metrics.map(({ key, label }) => <Card className="card" key={key}><p className="marketing-eyebrow">{label}</p><strong>{number(state.analytics.totals[key].value)}</strong><p className="muted">Измерено {state.analytics.totals[key].measured} из {state.analytics.sample_size} постов</p></Card>)}</div>
            <p className="muted">Последнее измерение: {fmtDate(state.analytics.collected_at)}. Период относится к дате публикации; просмотры не равны уникальному охвату.</p>
            {state.analytics.channel_snapshots.map((s) => <Card className="card" key={s.channel}><div className="cardHead"><h3>{s.channel}</h3><span className="muted">{fmtDate(s.collected_at)}</span></div><div className="marketing-post-metrics"><div><span>Подписчики</span><b>{number(s.subscribers)}</b><small>Изменение с прошлого снимка: {number(s.subscribers_change)}</small></div><div><span>Вовлечённость с пересылками · 7 дней</span><b>{s.engagement_percent === null ? '—' : `${s.engagement_percent}%`}</b><small>(Реакции + пересылки) / просмотры</small></div></div>{s.truncated && <p className="note">Неполная выборка: достигнут лимит сбора сообщений.</p>}<p className="muted">{s.comparison_note}</p></Card>)}
            <div className="marketing-grid"><Card className="card"><h3>Следующие действия</h3><div className="marketing-checklist"><button onClick={() => setScreen('research')}><Compass size={18} /><span>{state.sources.web_search ? 'Исследовать рынок и возможности' : 'Подключить веб-поиск для исследования'}<small>Ниша, география и подтверждённые источники</small></span><ArrowUpRight size={16} /></button>
              <button onClick={() => setScreen('content')}><BarChart3 size={18} /><span>{state.analytics.sample_size ? 'Проверить эффективность контента' : 'Собрать показатели Telegram'}<small>Единая статистика постов и каналов</small></span><ArrowUpRight size={16} /></button>
              <button onClick={() => setScreen('hypotheses')}><FlaskConical size={18} /><span>Выбрать следующий эксперимент<small>{state.hypotheses.filter((h) => h.status === 'proposed').length} предложенных гипотез</small></span><ArrowUpRight size={16} /></button></div></Card>
              <Card className="card"><h3>Заявки и продажи</h3><Badge variant="secondary">Источник не подключён</Badge><p className="marketing-empty-value">Нет данных</p><p className="muted">Для оценки влияния на бизнес нужны заявки, продажи и источник перехода — например, CRM и UTM-метки.</p></Card></div>
            {state.documents[0] && <><h3>Последний результат · {kindNames[state.documents[0].kind]}</h3><DocumentView item={state.documents[0]} /></>}
            <Card className="card"><h3>Контекст исследования</h3>{state.permissions.manage ? <ProfileForm value={state.profile} busy={busy} save={(v) => act(() => workspaceApi.profile(id, v), 'Контекст сохранён')} /> : <dl className="marketing-dl"><dt>Ниша</dt><dd>{state.profile.niche || 'Не задана'}</dd><dt>География</dt><dd>{state.profile.geography || 'Не задана'}</dd><dt>Цели</dt><dd>{state.profile.goals || 'Администратор может заполнить контекст компании'}</dd></dl>}</Card>
          </>}

          {(screen === 'research' || screen === 'competitors') && <>
            <Card className="card"><h3>{screen === 'research' ? 'Что происходит на нашем рынке' : 'На чём конкурируют другие'}</h3><p className="muted">{screen === 'research' ? 'Тенденции, риски и точки роста с датой исследования и ссылками.' : 'Сравнение позиционирования и маркетинговой активности подтверждённых конкурентов по публичным источникам.'}</p>
              {!state.sources.web_search && <p className="note">Веб-поиск не подключён. Администратору сервиса нужно настроить TAVILY_API_KEY.</p>}
              <Label>Фокус исследования<Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={2000} placeholder="Какие продукты, сегменты или вопросы изучить" rows={3} /></Label>
              {canWrite && <Button disabled={busy || !state.sources.web_search || (screen === 'competitors' && !state.competitors.some((c) => c.confirmed))} onClick={() => void start(screen)}>Запустить {screen === 'research' ? 'анализ рынка' : 'анализ конкурентов'}</Button>}
            </Card>
            {screen === 'competitors' && <><div className="marketing-grid">{state.competitors.map((c) => <Card key={c.id} className="card"><div className="cardHead"><h3>{c.name}</h3><Badge variant="secondary">{c.confirmed ? 'Подтверждён' : 'Предложен AI'}</Badge></div>
              {c.website && <p><SourceLink url={c.website}>Сайт ↗</SourceLink></p>}{c.telegram && <p><SourceLink url={c.telegram}>Telegram ↗</SourceLink></p>}<p className="muted">{c.notes}</p>
              {canWrite && <div className="row">{!c.confirmed && <Button disabled={busy} onClick={() => void action(() => workspaceApi.confirmCompetitor(id, c.id))}>Подтвердить конкурента</Button>}<ConfirmAction label="Удалить конкурента" description="Конкурент будет исключён из будущих исследований. Сохранённые отчёты останутся." onConfirm={() => act(() => workspaceApi.deleteCompetitor(id, c.id))}>Удалить</ConfirmAction></div>}
            </Card>)}</div>{canWrite && <Card className="card"><h3>Добавить конкурента</h3><CompetitorForm busy={busy} save={(v) => act(() => workspaceApi.addCompetitor(id, v), 'Конкурент добавлен')} /></Card>}</>}
            {renderDocuments(screen)}
          </>}

          {screen === 'content' && <>
            <Card className="card"><h3>Собрать показатели Telegram</h3><p className="muted">Сбор публикаций за последние 7 дней. Включает посты, созданные вне приложения. Для сбора администратор подключает Telegram-аккаунт в разделе «Задачи».</p>
              <div className="row"><Label>Канал для сбора<select className="task-select" value={syncChannel} onChange={(e) => setSyncChannel(e.target.value)}><option value="">Выберите канал</option>{state.channels.map((c) => <option key={c.id} value={c.id}>{c.channel_id}</option>)}</select></Label>{canWrite && <Button disabled={busy || !syncChannel} onClick={() => void action(() => workspaceApi.start(id, 'sync', days, channel, '', Number(syncChannel)), 'Сбор статистики запущен')}>Собрать статистику</Button>}</div>
            </Card>
            <Card className="card"><h3>Эффективность форматов</h3><p className="muted">Медиана доли реакций: реакции / просмотры × 100%. Сравниваем внутри канала. Возраст публикаций может влиять на результат.</p>
              {state.analytics.formats.length ? <div className="marketing-table-wrap"><table className="marketing-table"><thead><tr><th>Канал / формат</th><th>Постов</th><th>Доля реакций</th></tr></thead><tbody>{state.analytics.formats.map((f, i) => <tr key={i}><td>{f.channel}<br /><b>{formatNames[f.format] || f.format}</b>{!f.comparable && <small>Малая выборка</small>}</td><td>{f.posts}</td><td>{f.median_reaction_rate}%</td></tr>)}</tbody></table></div> : <p className="note">Для сравнения форматов нужны просмотры и реакции, измеренные с разницей не более суток.</p>}
            </Card>
            <details className="marketing-sources"><summary>Как читать показатели</summary><ul>{state.analytics.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
            {state.analytics.snapshot_history.length > 0 && <Card className="card"><h3>История снимков каналов</h3><p className="muted">Снимки скользящих окон за 7 дней могут перекрываться. Это история измерений, а не прирост просмотров за день.</p><div className="marketing-table-wrap"><table className="marketing-table"><thead><tr><th>Снимок / канал</th><th>Подписчики</th><th>Просмотры</th></tr></thead><tbody>{state.analytics.snapshot_history.slice(0, 20).map((s, i) => <tr key={i}><td>{fmtDate(s.collected_at)}<small>{s.channel}</small></td><td>{number(s.subscribers)}</td><td>{number(s.views)}</td></tr>)}</tbody></table></div></Card>}
            {!state.analytics.posts.length && <Empty title="Показателей пока нет">Выберите канал и запустите сбор либо внесите измерения во вкладке «Статистика».</Empty>}
            {state.analytics.posts.slice(0, shownPosts).map((p) => <Card key={p.id} className="card"><div className="cardHead"><Badge variant="secondary">{formatNames[p.format] || p.format}</Badge><span className="muted">{fmtDate(p.published_at)}</span></div><p className="muted">{p.channel || 'Канал не зафиксирован'} · #{p.external_id || p.post_id}</p><p className="marketing-post-text">{p.text || 'Текст публикации недоступен'}</p><div className="marketing-post-metrics">{metrics.map(({ key, label }) => <div key={key}><span>{label}</span><b>{number(p.metrics[key].value)}</b><small>{p.metrics[key].source === 'manual' ? 'Вручную' : p.metrics[key].source ? 'Telegram' : 'Нет данных'} · {fmtDate(p.metrics[key].observed_at)}</small></div>)}</div><p className="muted">Доля реакций: {p.reaction_rate === null ? 'Нет сопоставимых данных' : `${p.reaction_rate}%`}</p></Card>)}
            {state.analytics.posts.length > shownPosts && <Button variant="outline" onClick={() => setShownPosts((v) => v + 20)}>Показать ещё публикации</Button>}
          </>}

          {screen === 'hypotheses' && <>
            <Card className="card"><h3>От наблюдения к эксперименту</h3><p className="muted">Каждая гипотеза содержит основание, действие, метрику и критерий успеха. При нехватке данных AI предложит, что измерить.</p>{canWrite && <Button disabled={busy} onClick={() => void start('hypotheses')}>Сформировать гипотезы</Button>}</Card>
            {!state.hypotheses.length && <Empty title="Гипотез пока нет">Соберите показатели или исследуйте рынок, затем сформируйте проверяемые предложения.</Empty>}
            {state.hypotheses.map((h) => <HypothesisCard key={`${h.id}:${h.updated_at}`} item={h} busy={busy} writable={canWrite} act={action} id={id} />)}
            {renderDocuments('hypotheses')}
          </>}

          {screen === 'strategy' && <>
            <Card className="card"><h3>Стратегия, которую можно выполнить</h3><p className="muted">Цели, аудитория, позиционирование, каналы и KPI на основе знаний компании, исследований и измерений. Новые версии сохраняются отдельно.</p><div className="row">{canWrite && <><Button disabled={busy} onClick={() => void start('strategy')}>Подготовить стратегию</Button><Button variant="outline" disabled={busy} onClick={() => void start('plan')}>Составить план на 7 дней</Button></>}</div></Card>
            {state.documents.filter((d) => d.kind === 'strategy').slice(0, 1).map((d) => <div key={d.id} className="space-y-3"><Badge variant="secondary">{d.approved_at ? `Утверждена ${fmtDate(d.approved_at)}` : 'Проект стратегии · требуется согласование'}</Badge><DocumentView item={d} />{!d.approved_at && state.permissions.manage && <Button disabled={busy} onClick={() => void action(() => workspaceApi.approve(id, d.id), 'Стратегия утверждена')}>Утвердить стратегию</Button>}</div>)}
            {!state.documents.some((d) => d.kind === 'strategy') && <Empty title="Стратегия ещё не подготовлена">Заполните контекст бизнеса и создайте первую версию.</Empty>}
            <h3>Контент-план · предложения тем</h3><p className="muted">День — относительный номер в плане. Подготовка материала не назначает публикацию: пост поступит администратору на согласование.</p>
            {state.plan.filter((p) => p.document_id === state.plan[0]?.document_id).sort((a, b) => a.day - b.day).map((p) => <Card className="card" key={p.id}><div className="cardHead"><Badge variant="secondary">День {p.day}</Badge><span className="muted">{p.rubric} · {p.format}</span></div><h3>{p.topic}</h3><p>{p.rationale}</p>{canWrite && <Button className="mt-3" disabled={busy || !!p.task_id} onClick={() => void action(() => workspaceApi.prepare(id, 'plan', p.id), 'Материал отправлен в подготовку и потребует согласования')}>{p.task_id ? 'Передан в подготовку' : 'Подготовить материал'}</Button>}</Card>)}
            <details className="marketing-history"><summary>История стратегий и планов</summary>{state.documents.filter((d) => d.kind === 'strategy' || d.kind === 'plan').map((d) => <DocumentView key={d.id} item={d} />)}</details>
          </>}

          {screen === 'report' && <>
            <Card className="card"><h3>Цифры, выводы и конкретные действия</h3><p className="muted">Отчёт сохраняет показатели на момент анализа. Для заявок и продаж показываем «Нет данных», пока источник не подключён.</p>{canWrite && <Button disabled={busy} onClick={() => void start('report')}>Сформировать отчёт</Button>}</Card>
            <ReportSchedule key={JSON.stringify(state.schedule)} state={state} id={id} busy={busy} act={action} />
            {renderDocuments('report')}
          </>}

          <details className="marketing-history"><summary>История запусков · {state.runs.length}</summary>{state.runs.map((r) => <div className="marketing-run" key={r.id}><div><b>{kindNames[r.kind] || r.kind}</b><p className="muted">#{r.id} · {statuses[r.status] || r.status} · {fmtDate(r.finished_at || r.started_at)}</p>{r.error && <p className="error">{r.error}</p>}</div>{r.post_id && <Button variant="outline" disabled={busy} onClick={() => { setExpanded(expanded === r.post_id ? null : r.post_id); }}>Пост #{r.post_id}</Button>}{r.post_id && expanded === r.post_id && <GeneratedPreview companyId={id} postId={r.post_id} />}</div>)}</details>
          {!!docs.length && <p className="muted">Сохранено версий в этом разделе: {docs.length}. Новые данные могут требовать обновления анализа.</p>}
        </div>
      </div>
    </>}
  </section>;
}
function GeneratedPreview({ companyId, postId }: { companyId: number; postId: number }) {
  const [post, , error] = useLoad(() => api.taskPost(postId, companyId), [companyId, postId]);
  return <div className="marketing-generated">{error && <p role="alert" className="error">{error}</p>}{post ? <><p className="note">Статус: {post.status === 'pending_approval' ? 'Ожидает согласования администратора' : post.status}</p>{post.image_url && <img className="postImg" src={post.image_url} alt="Материал на согласование" />}<p className="postText">{post.text}</p></> : !error && <p>Загружаем материал…</p>}</div>;
}
