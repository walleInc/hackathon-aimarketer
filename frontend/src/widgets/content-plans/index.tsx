import { useEffect, useState } from 'react';
import { api, StatusChip, type ContentPlanInput, type ContentPlanItem, type ContentPlanItemInput } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';
import { Button, Card, Label, Input, Textarea, ConfirmAction, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/shared/ui';
import { PostComposer } from '@/widgets/post-composer';

function defaults(): ContentPlanInput {
  const now = new Date(); const end = new Date(now); end.setDate(end.getDate() + 6);
  const local = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return {title: '', start_date: local(now), end_date: local(end), posts_per_day: 1, wishes: ''};
}
const dateLabel = (value: string) => new Date(value + 'T12:00:00').toLocaleDateString('ru-RU', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
const stateLabel: Record<string, string> = {generating: 'Генерируется', ready: 'Готов', failed: 'Есть ошибки', pending: 'Ожидает генерации', running: 'Генерируется', done: 'Готово'};

export function ContentPlans({id, canEdit}: {id: number; canEdit: boolean}) {
  const [plans, reloadPlans, listError] = useLoad(() => api.contentPlans(id), [id]);
  const [selected, setSelected] = useState(0);
  const [plan, reloadPlan, detailError] = useLoad(() => selected ? api.contentPlan(id, selected) : Promise.resolve(null), [id, selected]);
  const [form, setForm] = useState(defaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<{item?: ContentPlanItem; values: ContentPlanItemInput} | null>(null);
  const [template, setTemplate] = useState<ContentPlanItem | undefined>();
  const [openedPost, setOpenedPost] = useState<number | null>(null);
  const [post, , postError] = useLoad(() => openedPost ? api.taskPost(openedPost, id) : Promise.resolve(null), [id, openedPost]);
  useEffect(() => {
    if (plan?.status !== 'generating' && !plans?.some((p) => p.status === 'generating')) return;
    const timer = window.setInterval(() => { reloadPlans(); if (selected) reloadPlan(); }, 4000);
    return () => window.clearInterval(timer);
  }, [plan?.status, plans, selected, reloadPlans, reloadPlan]);
  const reload = () => { reloadPlan(); reloadPlans(); };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <div className="space-y-4">
    <h2>Контент-планы компании</h2>
    {canEdit && <Card className="card"><form onSubmit={(e) => { e.preventDefault(); void run(async () => {
      const result = await api.createContentPlan(form); setSelected(result.id); setTemplate(undefined); reloadPlans();
    }); }}><fieldset disabled={busy} className="space-y-3">
      <h3>Создать контент-план с ИИ</h3>
      <Label>Название плана<Input value={form.title} onChange={(e) => setForm({...form, title: e.target.value})} maxLength={200} required /></Label>
      <div className="row2"><Label>Начало периода<Input type="date" value={form.start_date} onChange={(e) => setForm({...form, start_date: e.target.value})} required /></Label>
        <Label>Конец периода<Input type="date" min={form.start_date} value={form.end_date} onChange={(e) => setForm({...form, end_date: e.target.value})} required /></Label></div>
      <Label>Постов в день<Input type="number" min={1} max={10} step={1} value={form.posts_per_day} onChange={(e) => setForm({...form, posts_per_day: Number(e.target.value)})} required /></Label>
      <Label>Пожелания к плану<Textarea value={form.wishes} onChange={(e) => setForm({...form, wishes: e.target.value})} maxLength={3000} placeholder="Цели, темы, продукты и форматы" /></Label>
      <p className="muted">До 31 дня включительно, 1–10 постов в день. Генерация идёт в фоне с учётом базы знаний и бренда.</p>
      <Button disabled={busy || !form.title.trim()}>{busy ? 'Создаём…' : 'Сгенерировать план'}</Button>
    </fieldset></form></Card>}
    {(error || listError || detailError) && <p role="alert" className="error">{error || listError || detailError}</p>}
    <Label>Выбрать план<select className="task-select" value={selected} onChange={(e) => { setSelected(Number(e.target.value)); setTemplate(undefined); }}>
      <option value={0}>Выберите контент-план</option>{(plans ?? []).map((p) => <option value={p.id} key={p.id}>{p.title} · {p.start_date} — {p.end_date}</option>)}
    </select></Label>
    {plans?.length === 0 && <p className="muted">Контент-планов пока нет.</p>}
    {plan && <>
      <Card className="card space-y-2"><h3>{plan.title}</h3><p>{stateLabel[plan.status]} · Дней готово: {plan.completed_days} из {plan.total_days}</p>
        <progress className="w-full" aria-label="Прогресс генерации" value={plan.completed_days} max={plan.total_days} />
        {canEdit && plan.days.some((d) => d.status === 'failed') && <Button disabled={busy} onClick={() => void run(async () => { await api.retryContentPlan(plan.id); reload(); })}>Повторить неготовые дни</Button>}
        <Button variant="outline" onClick={reload}>Обновить план</Button>
        <p className="muted">Изменения общие для команды. После ручных правок количество задач по дням может отличаться от исходного.</p>
      </Card>
      {plan.days.map((day) => <Card className="card space-y-3" key={day.date}>
        <h3>{dateLabel(day.date)}</h3><p className="muted">{stateLabel[day.status]}</p>
        {day.error && <p role="alert" className="error">{day.error}</p>}
        {plan.items?.filter((i) => i.planned_date === day.date).map((item) => <div className="plan-item space-y-2" key={item.id}>
          <h4>{item.title}</h4><p className="postText">{item.description}</p>
          {item.posts.map((p) => <Button key={p.id} variant="link" onClick={() => setOpenedPost(p.id)}>Пост #{p.id} · <StatusChip status={p.status} /></Button>)}
          {canEdit && <div className="row">
            <Button onClick={() => { setTemplate(item); window.setTimeout(() => document.getElementById('post-composer')?.scrollIntoView({behavior: 'smooth', block: 'start'}), 0); }}>Создать пост по задаче</Button>
            <Button variant="outline" onClick={() => { setError(''); setEditor({item, values: {planned_date: item.planned_date, title: item.title, description: item.description, position: item.position}}); }}>Изменить задачу</Button>
            <ConfirmAction label={`Удалить задачу ${item.title}`} description="Задача исчезнет из плана. Уже созданные посты сохранятся." onConfirm={async () => { await api.deleteContentPlanItem(item.id, item.version); if (template?.id === item.id) setTemplate(undefined); reload(); }}>Удалить задачу</ConfirmAction>
          </div>}
        </div>)}
        {canEdit && <Button variant="outline" onClick={() => { setError(''); setEditor({values: {planned_date: day.date, title: '', description: '', position: plan.items?.filter((i) => i.planned_date === day.date).length ?? 0}}); }}>Добавить задачу</Button>}
      </Card>)}
    </>}
    {template && <PostComposer key={template.id} id={id} initialItem={template} onCreated={reload} />}
    <Dialog open={editor !== null} onOpenChange={(open) => { if (!open && !busy) setEditor(null); }}><DialogContent>
      <DialogHeader><DialogTitle>{editor?.item ? 'Редактировать задачу' : 'Новая задача'}</DialogTitle><DialogDescription>Измените тему, задание или дату внутри периода плана.</DialogDescription></DialogHeader>
      {editor && plan && <form onSubmit={(e) => { e.preventDefault(); void run(async () => {
        if (editor.item) await api.editContentPlanItem(editor.item.id, {...editor.values, version: editor.item.version});
        else await api.addContentPlanItem(plan.id, editor.values);
        if (template?.id === editor.item?.id) setTemplate(undefined);
        setEditor(null); reload();
      }); }}><fieldset disabled={busy} className="space-y-3">
        <Label>Дата задачи<Input type="date" min={plan.start_date} max={plan.end_date} value={editor.values.planned_date} onChange={(e) => setEditor({...editor, values: {...editor.values, planned_date: e.target.value}})} required /></Label>
        <Label>Тема задачи<Input maxLength={200} value={editor.values.title} onChange={(e) => setEditor({...editor, values: {...editor.values, title: e.target.value}})} required /></Label>
        <Label>Описание задачи<Textarea maxLength={3000} rows={5} value={editor.values.description} onChange={(e) => setEditor({...editor, values: {...editor.values, description: e.target.value}})} required /></Label>
        {error && <p role="alert" className="error">{error}</p>}
        <Button disabled={busy || !editor.values.title.trim() || !editor.values.description.trim()}>Сохранить задачу</Button>
      </fieldset></form>}
    </DialogContent></Dialog>
    <Dialog open={openedPost !== null} onOpenChange={(open) => { if (!open) setOpenedPost(null); }}><DialogContent>
      <DialogHeader><DialogTitle>Пост #{openedPost}</DialogTitle><DialogDescription>Материал, созданный по задаче контент-плана.</DialogDescription></DialogHeader>
      {postError && <p role="alert" className="error">{postError}</p>}{post && <><StatusChip status={post.status} /><p className="postText">{post.text}</p>{post.image_url && <img className="postImg" src={post.image_url} alt="Иллюстрация поста" />}</>}
    </DialogContent></Dialog>
  </div>;
}
