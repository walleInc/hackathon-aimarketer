import { useEffect, useState } from 'react';
import { api, PLATFORM_RU, StatusChip, type ContentPlanItem, type Post } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';
import { Button, Card, Input, Label, Textarea } from '@/shared/ui';

export function PostComposer({ id, initialItem, onCreated }: {id: number; initialItem?: ContentPlanItem; onCreated?: () => void}) {
  const [plans, , listError] = useLoad(() => api.contentPlans(id), [id]);
  const [platforms] = useLoad(api.platforms, []);
  const [platform, setPlatform] = useState('');
  const [planId, setPlanId] = useState(initialItem?.plan_id ?? 0);
  const [day, setDay] = useState(initialItem?.planned_date ?? '');
  const [itemId, setItemId] = useState<number | undefined>(initialItem?.id);
  const [prompt, setPrompt] = useState(initialItem ? `${initialItem.title}\n${initialItem.description}` : '');
  const [plan, , planError] = useLoad(() => planId ? api.contentPlan(id, planId) : Promise.resolve(null), [id, planId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [post, setPost] = useState<Post | null>(null);
  useEffect(() => {
    if (initialItem) {
      setPlanId(initialItem.plan_id); setDay(initialItem.planned_date); setItemId(initialItem.id);
      setPrompt(`${initialItem.title}\n${initialItem.description}`); setPost(null);
    }
  }, [initialItem?.id]);
  const choose = (value: string) => {
    const item = plan?.items?.find((i) => i.id === Number(value));
    setItemId(item?.id); setPrompt(item ? `${item.title}\n${item.description}` : ''); setPost(null);
  };
  return <Card className="card space-y-3" id="post-composer">
    <h3>Создать пост</h3>
    <form onSubmit={async (event) => {
      event.preventDefault(); setBusy(true); setError(''); setPost(null);
      try { setPost(await api.generatePost(prompt.trim(), itemId, platform || undefined)); onCreated?.(); }
      catch (e) { setError((e as Error).message); }
      finally { setBusy(false); }
    }}><fieldset disabled={busy} className="space-y-3">
      <Label>Контент-план<select className="task-select" value={planId} onChange={(e) => { setPlanId(Number(e.target.value)); setDay(''); setItemId(undefined); setPrompt(''); }}>
        <option value={0}>Без шаблона</option>{(plans ?? []).map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
      </select></Label>
      {planId > 0 && <>
        <Label>Дата задачи<Input type="date" value={day} min={plan?.start_date} max={plan?.end_date} onChange={(e) => { setDay(e.target.value); setItemId(undefined); setPrompt(''); }} required /></Label>
        <Label>Задача плана<select className="task-select" value={itemId ?? ''} required onChange={(e) => choose(e.target.value)}>
          <option value="">Выберите задачу</option>{plan?.items?.filter((i) => i.planned_date === day).map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
        </select></Label>
      </>}
      <Label>Площадка<select className="task-select" value={platform} onChange={(e) => setPlatform(e.target.value)}>
        <option value="">Авто (по подключённым)</option>
        {(platforms ?? []).map((p) => <option key={p} value={p}>{PLATFORM_RU[p] ?? p}</option>)}
      </select></Label>
      <Label>Задание для поста<Textarea rows={5} maxLength={4000} value={prompt} onChange={(e) => setPrompt(e.target.value)} required /></Label>
      <p className="muted">Уточните задание перед генерацией. Пост будет отправлен на согласование; дата плана не назначает публикацию.</p>
      <Button disabled={busy || !prompt.trim()}>{busy ? 'Генерируем…' : 'Сгенерировать пост'}</Button>
    </fieldset></form>
    {(error || listError || planError) && <p role="alert" className="error">{error || listError || planError}</p>}
    {post && <div className="space-y-2"><p>Пост #{post.id} · {PLATFORM_RU[post.platform] ?? post.platform} · <StatusChip status={post.status} /></p><p className="postText">{post.text}</p>
      {post.image_url && <img className="postImg" src={post.image_url} alt="Иллюстрация поста" />}</div>}
  </Card>;
}
