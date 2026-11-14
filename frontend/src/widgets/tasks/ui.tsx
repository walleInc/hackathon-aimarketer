import { useEffect, useState, type FormEvent } from 'react';
import { api, fmtDate, StatusChip, type TaskItem, type TaskInput, type TaskRun, type Post } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';
import { Button, Card, Input, Textarea, Label, ConfirmAction } from '@/shared/ui';
import { TelegramConnection } from './telegram-connection';

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const RUN_STATUS: Record<string, string> = { pending: 'Ожидает', running: 'Выполняется', succeeded: 'Готово', failed: 'Ошибка', cancelled: 'Отменено', skipped: 'Пропущено' };
const initial = (): TaskInput => ({ kind: 'post', prompt: '', schedule_kind: 'daily', interval_minutes: 1440,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', local_time: '09:00', weekdays: [0] });
const formatInZone = (value: string | null, zone: string) => value ? new Date(value.endsWith('Z') ? value : value + 'Z').toLocaleString('ru-RU', { timeZone: zone }) : '—';
function scheduleLabel(task: TaskItem) {
  if (task.schedule_kind === 'once') return 'Один раз';
  if (task.schedule_kind === 'daily') return `Ежедневно в ${task.local_time}`;
  if (task.schedule_kind === 'weekly') return `${task.weekdays.split(',').map((d) => DAYS[Number(d)]).join(', ')} в ${task.local_time}`;
  return `Каждые ${task.interval_minutes / 60} ч.`;
}

function GeneratedPost({ id, companyId }: { id: number; companyId: number }) {
  const [post, reload, loadError] = useLoad(() => api.taskPost(id, companyId), [id]);
  const [me] = useLoad(api.me, []);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [when, setWhen] = useState('');
  const action = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr('');
    try { await fn(); reload(); } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  if (!post) return <p role={loadError ? 'alert' : undefined}>{loadError || 'Загрузка поста…'}</p>;
  return <div className="space-y-3">
    <p>Пост #{post.id} · <StatusChip status={post.status} /></p>
    {post.image_url && <img className="postImg" src={post.image_url} alt="Изображение публикации" />}
    <p className="postText">{post.text}</p>
    <p>Публикация: {fmtDate(post.scheduled_at)}</p>
    {post.needs_reschedule && <p className="error">Время публикации прошло. Выберите новое время.</p>}
    {me?.role === 'approver' && post.status === 'pending_approval' && <div className="row">
      <Button disabled={busy} onClick={() => void action(() => api.decide(post.id, 'approve', '', post.version))}>Одобрить пост</Button>
      <Button variant="outline" disabled={busy} onClick={() => void action(() => api.decide(post.id, 'reject', '', post.version))}>Отклонить пост</Button>
    </div>}
    {me?.role === 'approver' && post.needs_reschedule && <form className="space-y-3" onSubmit={(event) => {
      event.preventDefault(); void action(() => api.reschedulePost(post.id, new Date(when).toISOString(), post.version));
    }}>
      <Label>Новое время публикации (часовой пояс устройства)<Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required /></Label>
      <Button disabled={busy}>Перенести публикацию</Button>
    </form>}
    {(err || loadError) && <p role="alert" className="error">{err || loadError}</p>}
  </div>;
}

function RunHistory({ task, companyId }: { task: TaskItem; companyId: number }) {
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(true);
  const [expandedPost, setExpandedPost] = useState<number | null>(null);
  const load = async (before?: number) => {
    setBusy(true); setError('');
    try {
      const result = await api.taskRuns(task.id, before);
      setRuns((old) => before ? [...old, ...result] : result);
      setMore(result.length === 20);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, [task.id]);
  return <div className="space-y-3 mt-4">
    <div className="row"><b>История запусков</b><Button variant="outline" disabled={busy} onClick={() => void load()}>Обновить результаты</Button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!runs.length && !busy && <p className="muted">Запусков пока нет.</p>}
    {runs.map((run) => <div className="task-run" key={run.id}>
      <p><b>{RUN_STATUS[run.status] || run.status}</b> · {formatInZone(run.scheduled_for, task.timezone)} ({task.timezone})</p>
      {run.started_at && <p className="muted">Начат: {fmtDate(run.started_at)} · Завершён: {fmtDate(run.finished_at)}</p>}
      {run.error && <p role="alert" className="error">{run.error}</p>}
      {run.result && <p className="postText">{run.result}</p>}
      {run.sources.length > 0 && <ul>{run.sources.map((source, i) => <li key={i}><a href={source.url} target="_blank" rel="noreferrer">{source.title || source.url}</a></li>)}</ul>}
      {Object.keys(run.metrics).length > 0 && <details><summary>Исходные показатели</summary><pre className="task-metrics">{JSON.stringify(run.metrics, null, 2)}</pre></details>}
      {run.post_id && <><Button variant="outline" onClick={() => setExpandedPost(expandedPost === run.post_id ? null : run.post_id)}>Открыть пост #{run.post_id}</Button>
        {expandedPost === run.post_id && <GeneratedPost id={run.post_id} companyId={companyId} />}</>}
    </div>)}
    {more && runs.length > 0 && <Button disabled={busy} variant="outline" onClick={() => void load(runs[runs.length - 1].id)}>Ещё запуски</Button>}
  </div>;
}

export function Tasks({ id }: { id: number }) {
  const [tasks, reload, loadError] = useLoad(() => api.tasks(id), [id]);
  const [catalog, , catalogError] = useLoad(api.taskCatalog, []);
  const [me] = useLoad(api.me, []);
  const [connections, reloadConnections, connectionError] = useLoad(() => api.telegramAnalytics(id), [id]);
  const [form, setForm] = useState<TaskInput>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [openHistory, setOpenHistory] = useState<number | null>(null);
  useEffect(() => { const timer = window.setInterval(reload, 30000); return () => window.clearInterval(timer); }, [reload]);
  const change = <K extends keyof TaskInput>(key: K, value: TaskInput[K]) => setForm((f) => ({ ...f, [key]: value }));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api.createTask(id, { ...form, prompt: form.prompt.trim(), first_run_local: ['once', 'interval'].includes(form.schedule_kind) ? form.first_run_local : undefined,
        channel_id: form.kind === 'statistics' ? form.channel_id : undefined });
      setForm(initial()); reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const canCreate = me?.role === 'approver' || me?.role === 'member';
  return <div className="space-y-4">
    {(loadError || error || catalogError || connectionError) && <p role="alert" className="error">{error || loadError || catalogError || connectionError}</p>}
    <div className="split">
      <div className="space-y-4">
        {canCreate ? <Card className="card"><form onSubmit={submit}><fieldset disabled={busy} className="space-y-4">
          <h3>Задача по расписанию</h3>
          <Label>Тип задачи<select className="task-select" value={form.kind} onChange={(e) => change('kind', e.target.value as TaskInput['kind'])}>
            {(catalog ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></Label>
          <p className="muted">{catalog?.find((item) => item.id === form.kind)?.description}</p>
          <Label>Уточнение задачи<Textarea rows={3} maxLength={2000} placeholder="Тема, продукт, рынок или конкуренты" value={form.prompt} onChange={(e) => change('prompt', e.target.value)} /></Label>
          <Label>Расписание<select className="task-select" value={form.schedule_kind} onChange={(e) => change('schedule_kind', e.target.value as TaskInput['schedule_kind'])}>
            <option value="interval">Каждые N часов</option><option value="daily">Ежедневно</option><option value="weekly">По дням недели</option><option value="once">Один раз</option>
          </select></Label>
          <Label>Часовой пояс<Input value={form.timezone} onChange={(e) => change('timezone', e.target.value)} placeholder="Europe/Riga" required list="task-timezones" /></Label>
          <datalist id="task-timezones">{['Europe/Riga', 'Europe/Moscow', 'Europe/Kyiv', 'Asia/Almaty', 'UTC'].map((zone) => <option key={zone} value={zone} />)}</datalist>
          {form.schedule_kind === 'interval' && <Label>Периодичность, часов<Input type="number" min={1} max={8760} step={1} value={form.interval_minutes / 60} onChange={(e) => change('interval_minutes', Number(e.target.value) * 60)} required /></Label>}
          {['once', 'interval'].includes(form.schedule_kind) ? <Label>{form.kind === 'post' ? 'Первая публикация' : 'Первый запуск'} ({form.timezone})<Input type="datetime-local" value={form.first_run_local ?? ''} onChange={(e) => change('first_run_local', e.target.value)} required /></Label> :
            <Label>{form.kind === 'post' ? 'Время публикации' : 'Время запуска'}<Input type="time" value={form.local_time} onChange={(e) => change('local_time', e.target.value)} required /></Label>}
          {form.schedule_kind === 'weekly' && <fieldset><legend>Дни недели</legend><div className="row">{DAYS.map((day, i) => <label className="task-day" key={day}>
            <input type="checkbox" checked={form.weekdays.includes(i)} onChange={(e) => change('weekdays', e.target.checked ? [...form.weekdays, i] : form.weekdays.filter((d) => d !== i))} />{day}
          </label>)}</div></fieldset>}
          {form.kind === 'statistics' && <Label>Telegram-канал<select className="task-select" value={form.channel_id ?? ''} onChange={(e) => change('channel_id', Number(e.target.value))} required>
            <option value="">Выберите канал</option>{connections?.channels?.map((c) => <option key={c.id} value={c.id}>{c.channel_id}</option>)}
          </select></Label>}
          {form.kind === 'post' && <p className="muted">ИИ готовит пост за 24 часа до публикации, ближайший — сразу. Публикация требует согласования. При позднем одобрении нужно выбрать новое время.</p>}
          {form.kind === 'market' && connections && !connections.web_search_configured && <p className="error">Оператору нужно настроить ключ веб-поиска TAVILY_API_KEY.</p>}
          {form.kind === 'statistics' && !connections?.connected && <p className="error">Для выполнения нужен Telegram-аккаунт администратора компании.</p>}
          <Button type="submit" disabled={busy || !catalog?.length || (form.schedule_kind === 'weekly' && !form.weekdays.length)}>{busy ? 'Создаём…' : 'Создать задачу'}</Button>
        </fieldset></form></Card> : <Card className="card muted">Задачи создают сотрудники и администратор компании.</Card>}
        {connections && <TelegramConnection state={connections} reload={reloadConnections} />}
      </div>
      <div className="space-y-4">{tasks?.map((task) => <Card className="card" key={task.id}>
        <div className="cardHead"><b>{catalog?.find((item) => item.id === task.kind)?.name ?? 'Подготовка поста'}</b><span>{task.active ? 'Активна' : 'Приостановлена'}</span></div>
        <p>{task.prompt}</p><p>{scheduleLabel(task)} · {task.timezone}</p>
        <p className="muted">{task.kind === 'post' && task.schedule_kind !== 'legacy' ? 'Ближайшая публикация' : 'Следующее выполнение'}: {formatInZone(task.next_run, task.timezone)}</p>
        {task.kind === 'post' && task.next_run && task.schedule_kind !== 'legacy' && <p className="muted">Подготовка: {formatInZone(new Date(new Date(task.next_run + 'Z').getTime() - 86400000).toISOString(), task.timezone)}</p>}
        <p className="muted">Последнее планирование: {fmtDate(task.last_run)}</p>
        {task.last_result && <p>Последний результат: {RUN_STATUS[task.last_result.status] || task.last_result.status} · {task.last_result.error || task.last_result.result}</p>}
        <div className="row">
          <Button variant="outline" disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await api.toggleTask(task.id, !task.active); reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>{task.active ? 'Приостановить' : 'Включить'}</Button>
          <Button variant="outline" onClick={() => setOpenHistory(openHistory === task.id ? null : task.id)}>История и результаты</Button>
          <ConfirmAction label="Удалить задачу" description="Будущие запуски остановятся. Уже подготовленные посты и назначенные публикации сохранятся; их отменяют отдельно." onConfirm={async () => { await api.deleteTask(task.id); reload(); }}>Удалить</ConfirmAction>
        </div>
        {openHistory === task.id && <RunHistory task={task} companyId={id} />}
      </Card>)}{tasks?.length === 0 && <Card className="card muted">Задач по расписанию пока нет.</Card>}</div>
    </div>
  </div>;
}
