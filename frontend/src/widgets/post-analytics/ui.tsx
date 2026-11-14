import { useState } from 'react';
import { api, fmtDate, postMetricsSchema, PLATFORM_RU } from '@/entities/marketing';
import type { AnalyticsPost, MetricName } from '@/entities/marketing';
import { useEditorForm, useLoad } from '@/shared/lib';
import { Button, Card, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Label, Input, FormErrors } from '@/shared/ui';

const fields: { name: MetricName; label: string }[] = [
  { name: 'views', label: 'Просмотры' },
  { name: 'reactions', label: 'Реакции' },
  { name: 'forwards', label: 'Пересылки' },
  { name: 'comments', label: 'Комментарии' },
];
const number = (value: number | null) => value === null ? '—' : value.toLocaleString('ru-RU');
const defaults = { views: '', reactions: '', forwards: '', comments: '' };

export function PostAnalytics({ id, canEdit }: { id: number; canEdit: boolean }) {
  const [days, setDays] = useState(30);
  const [data, reload, loadError] = useLoad(() => api.postAnalytics(id, days), [id, days]);
  const [editor, setEditor] = useState<AnalyticsPost | null>(null);
  const [error, setError] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const form = useEditorForm(postMetricsSchema, defaults);
  const openEditor = (post: AnalyticsPost) => {
    setError('');
    // Пустые поля не отправляются и не затирают ранее полученные измерения.
    form.reset(defaults);
    setEditor(post);
  };
  const save = form.handleSubmit(async (values) => {
    if (!editor) return;
    const payload: Partial<Record<MetricName, number>> = {};
    for (const { name } of fields) if (values[name] !== '') payload[name] = Number(values[name]);
    setError('');
    try {
      await api.savePostMetrics(editor.id, payload);
      setEditor(null);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  });
  const recommend = async () => {
    setError(''); setAnalyzing(true);
    try { await api.recommendPosts(id, days); reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setAnalyzing(false); }
  };
  const measured = data?.posts.filter((post) => fields.some(({ name }) => post.metrics[name].value !== null)).length ?? 0;
  const advice = data?.ai_advice;
  return <section className="space-y-4" aria-label="Статистика публикаций">
    <div className="row">
      <h2>Статистика публикаций</h2>
      <Label>Период публикации
        <select className="rounded-md border bg-background p-2" value={days} disabled={analyzing}
          onChange={(event) => { setDays(Number(event.target.value)); setError(''); }}>
          <option value={7}>7 дней</option><option value={30}>30 дней</option>
          <option value={90}>90 дней</option><option value={0}>Всё время</option>
        </select>
      </Label>
      <Button type="button" variant="outline" onClick={reload}>Обновить</Button>
    </div>
    <p className="muted">Реакции поступают из Telegram, если бот — администратор канала и получает обновления реакций.
      Просмотры, пересылки и комментарии внесите из статистики канала. «—» означает, что данных нет.
      Счётчики относятся к основному сообщению поста; для длинного поста это сообщение с текстом.</p>
    {(loadError || error) && !editor && <p role="alert" className="error">{loadError || error}</p>}
    {!data && !loadError && <p role="status">Загружаем статистику…</p>}
    {data && <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Card className="card"><p className="muted">Опубликовано за период</p><strong className="text-2xl">{number(data.published_posts)}</strong></Card>
        {fields.map(({ name, label }) => <Card key={name} className="card">
          <p className="muted">{label}</p><strong className="text-2xl">{number(data.summary[name].total)}</strong>
          <p className="note">Измерено {data.summary[name].measured_posts} из {data.sample_size} постов</p>
        </Card>)}
        <Card className="card"><p className="muted">Реакции / просмотры</p>
          <strong className="text-2xl">{data.summary.reaction_rate === null ? '—' : `${data.summary.reaction_rate}%`}</strong>
          <p className="note">По {data.summary.rate_posts} постам с обоими показателями, измеренными с разницей до суток. Не доля уникальных читателей.</p>
        </Card>
      </div>
      <p className="note">Суммы рассчитаны по {data.sample_size} последним публикациям выбранного периода (максимум {data.max_posts}).
        Просмотры — сумма счётчиков, а не уникальный охват.</p>
      {data.unknown_publication_dates > 0 && <p className="note">У {data.unknown_publication_dates} старых постов неизвестно время публикации.
        Они доступны в периоде «Всё время» и исключены из сравнения подачи.</p>}
      {data.daily_publications.length > 0 && <Card className="card">
        <h3>Публикации по дням · МСК</h3>
        <div className="max-h-64 space-y-2 overflow-y-auto" role="img" aria-label="Количество публикаций по дням, значения указаны в каждой строке">
          {data.daily_publications.map((day) => <div key={day.date} className="flex items-center gap-3 text-sm">
            <span className="w-24 shrink-0">{day.date}</span>
            <div className="h-3 rounded bg-primary" style={{ width: `${Math.max(2, day.posts / Math.max(...data.daily_publications.map((row) => row.posts)) * 65)}%` }} />
            <span>{day.posts}</span>
          </div>)}
        </div>
      </Card>}
      <Card className="card space-y-3">
        <h3>Рекомендации по показателям</h3>
        {data.recommendations.map((item, index) => <div key={index}>
          <h4 className="font-medium">{item.title}</h4><p>{item.text}</p>
        </div>)}
      </Card>
      <Card className="card space-y-3">
        <div className="row"><h3>AI-анализ контента</h3>
          {canEdit && <Button type="button" disabled={analyzing || measured < 3 || (!!advice && !advice.stale)} onClick={() => void recommend()}>
            {analyzing ? 'Анализируем…' : advice?.stale ? 'Обновить рекомендации' : 'Получить AI-рекомендации'}
          </Button>}
        </div>
        <p className="note">Анализ до 50 последних постов с измерениями. Нужны данные хотя бы трёх постов.
          Запускается по кнопке, использует токены компании. Публикации и расписания остаются под вашим управлением.</p>
        {advice ? <>
          <p className="note">Сформировано {fmtDate(advice.created_at)}</p>
          {advice.stale && <p role="status" className="note">Показатели изменились. Рекомендации основаны на прежних измерениях.</p>}
          <p className="whitespace-pre-wrap break-words">{advice.text}</p>
        </> : <p className="muted">AI-анализ ещё не сформирован.</p>}
      </Card>
      <h3>Показатели постов</h3>
      {data.posts.length === 0 && <Card className="card muted">За выбранный период опубликованных постов нет.</Card>}
      {data.posts.map((post) => <Card className="card space-y-3" key={post.id}>
        <div className="meta">#{post.id} · {PLATFORM_RU[post.platform] ?? post.platform} · {post.channel_id || 'Канал не зафиксирован'} · {post.published_at ? fmtDate(post.published_at) : 'Дата публикации неизвестна'}</div>
        <p className="line-clamp-3 whitespace-pre-wrap break-words">{post.text}</p>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {fields.map(({ name, label }) => <div key={name}>
            <dt className="muted">{label}</dt><dd className="font-medium">{number(post.metrics[name].value)}</dd>
            {post.metrics[name].observed_at && <dd className="note">{post.metrics[name].source === 'telegram' ? 'Telegram' : 'Вручную'} · {fmtDate(post.metrics[name].observed_at!)}</dd>}
          </div>)}
        </dl>
        <p className="note">Реакции / просмотры: {post.reaction_rate === null ? '—' : `${post.reaction_rate}%`}</p>
        {canEdit && <Button type="button" variant="outline" onClick={() => openEditor(post)}>Внести показатели поста #{post.id}</Button>}
      </Card>)}
    </>}
    <Dialog open={editor !== null} onOpenChange={(open) => { if (!open && !form.formState.isSubmitting) setEditor(null); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>Показатели поста #{editor?.id}</DialogTitle>
          <DialogDescription>Внесите текущие счётчики из канала. Пустое поле сохранит прежнее измерение, 0 — измеренный ноль. Время измерения — момент сохранения.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={save}>
          {fields.map(({ name, label }) => <Label key={name}>{label}
            <Input type="text" inputMode="numeric" placeholder={editor?.metrics[name].value?.toString() ?? 'Нет данных'}
              {...form.register(name)} aria-invalid={!!form.formState.errors[name]} disabled={form.formState.isSubmitting} />
          </Label>)}
          <FormErrors errors={form.formState.errors} />
          {error && <p role="alert" className="error">{error}</p>}
          <DialogFooter><Button type="button" variant="outline" disabled={form.formState.isSubmitting} onClick={() => setEditor(null)}>Отмена</Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>Сохранить показатели</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </section>;
}
