import { useState } from 'react';
import type { Post } from "@/entities/marketing";
import { api, revisionSchema, StatusChip, fmtDate } from "@/entities/marketing";
import { useLoad, useEditorForm } from '@/shared/lib';
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Label,
  Input,
  Textarea,
  FormErrors,
} from '@/shared/ui';

export function Posts({ id, canDecide }: { id: number; canDecide: boolean }) {
  const [posts, reload, loadError] = useLoad(() => api.companyPosts(id), [id]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState<number | null>(null);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [editor, setEditor] = useState<{ post: Post; mode: 'text' | 'generate' | 'upload' | 'schedule' } | null>(null);
  const [value, setValue] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const openEditor = (post: Post, mode: 'text' | 'generate' | 'upload' | 'schedule') => {
    setErr('');
    setValue(mode === 'text' ? post.text : '');
    setFile(null);
    setEditor({ post, mode });
  };
  const save = async () => {
    if (!editor) return;
    if (editor.mode === 'upload' && (!file || file.size > 10 * 1024 * 1024)) {
      setErr('Выберите PNG, JPEG или WebP размером до 10 МБ');
      return;
    }
    if (editor.mode !== 'upload' && !value.trim()) {
      setErr('Заполните поле');
      return;
    }
    setBusy(editor.post.id);
    setErr('');
    try {
      const { post, mode } = editor;
      if (mode === 'schedule') await api.reschedulePost(post.id, new Date(value).toISOString(), post.version);
      else if (mode === 'text') await api.editPost(post.id, value, post.version);
      else if (mode === 'generate') await api.regeneratePostImage(post.id, value.trim(), post.version);
      else await api.uploadPostImage(post.id, file!, post.version);
      setEditor(null);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const form = useEditorForm(revisionSchema, { comment: '' });
  const decide = async (
    pid: number,
    decision: 'approve' | 'reject' | 'revise',
    comment = '',
  ) => {
    setBusy(pid);
    setErr('');
    try {
      await api.decide(pid, decision, comment, posts?.find((post) => post.id === pid)?.version);
      setRevisionId(null);
      form.reset();
    } catch (e) {
      setErr((e as Error).message);
    }
    setBusy(null);
    reload();
  };
  return (
    <div>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <Dialog
        open={revisionId !== null}
        onOpenChange={(open) => {
          if (!open && busy === null) setRevisionId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Доработка материала</DialogTitle>
            <DialogDescription>
              Опишите, что агенту нужно изменить в публикации.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={form.handleSubmit((values) =>
              revisionId !== null
                ? decide(revisionId, 'revise', values.comment)
                : Promise.resolve(),
            )}
            className="space-y-4"
          >
            <Label>
              Комментарий
              <Textarea
                {...form.register('comment')}
                aria-invalid={!!form.formState.errors.comment}
                autoFocus
              />
            </Label>
            <FormErrors errors={form.formState.errors} />
            {err && (
              <p role="alert" className="text-destructive">
                {err}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy !== null}
                onClick={() => setRevisionId(null)}
              >
                Отмена
              </Button>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                Отправить на доработку
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={editor !== null} onOpenChange={(open) => {
        if (!open && busy === null) setEditor(null);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editor?.mode === 'schedule' ? 'Перенести публикацию' : editor?.mode === 'text' ? 'Изменить текст' : editor?.mode === 'generate' ? 'Перегенерировать картинку' : 'Загрузить свою картинку'}</DialogTitle>
            <DialogDescription>
              {editor?.mode === 'schedule' ? 'Укажите новое будущее время публикации в часовом поясе устройства.' : editor?.mode === 'generate'
                ? 'Опишите новую картинку. Генерация оплачивается по тарифу провайдера. Текст поста сохранится.'
                : editor?.mode === 'text' ? 'Измените текст публикации. Картинка сохранится.' : 'PNG, JPEG или WebP до 10 МБ. Текст поста сохранится.'}
              {editor?.mode !== 'schedule' && ' После сохранения потребуется повторное согласование.'}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
            {editor?.mode === 'schedule' ? <Label>Новое время публикации<Input type="datetime-local" value={value} onChange={(event) => setValue(event.target.value)} required disabled={busy !== null} /></Label> : editor?.mode === 'upload' ? (
              <Label>Изображение
                <Input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy !== null}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
              </Label>
            ) : (
              <Label>{editor?.mode === 'text' ? 'Текст публикации' : 'Описание новой картинки'}
                <Textarea value={value} onChange={(event) => setValue(event.target.value)}
                  maxLength={editor?.mode === 'text' ? 4096 : 4000} rows={8} disabled={busy !== null} required autoFocus />
              </Label>
            )}
            {err && <p role="alert" className="error">{err}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={busy !== null} onClick={() => setEditor(null)}>Отмена</Button>
              <Button type="submit" disabled={busy !== null}>
                {busy !== null ? 'Сохраняем…' : editor?.mode === 'generate' ? 'Сгенерировать' : 'Сохранить'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {err && !editor && <Card className="card error">{err}</Card>}
      {(posts ?? []).map((p) => (
        <Card className="card" key={p.id}>
          <div className="meta">
            #{p.id} · v{p.version} · {p.platform} · {fmtDate(p.created_at)}{' '}
            <StatusChip status={p.status} />
          </div>
          {p.image_url && <img className="postImg" src={p.image_url} alt="" />}
          <p className="postText">{p.text}</p>
          {p.check_notes && <div className="note">🔎 {p.check_notes}</div>}
          {p.error && <div className="error">{p.error}</div>}
          {p.scheduled_at && <p className="muted">Публикация: {fmtDate(p.scheduled_at)}</p>}
          {p.needs_reschedule && <div className="note">Время публикации прошло. Выберите новое время.
            {canDecide && <Button type="button" disabled={busy !== null} onClick={() => openEditor(p, 'schedule')}>Перенести публикацию</Button>}
          </div>}
          {canDecide && ['draft', 'pending_approval', 'approved', 'revision', 'failed'].includes(p.status) && (
            <div className="row">
              <Button type="button" disabled={busy !== null} onClick={() => openEditor(p, 'text')}>📝 Изменить текст</Button>
              <Button type="button" disabled={busy !== null} onClick={() => openEditor(p, 'generate')}>🎨 Перегенерировать картинку</Button>
              <Button type="button" disabled={busy !== null} onClick={() => openEditor(p, 'upload')}>📎 Загрузить свою картинку</Button>
            </div>
          )}
          {canDecide && p.status === 'pending_approval' && (
            <div className="row">
              <Button
                type="button"
                variant="default"
                disabled={busy !== null}
                onClick={() => decide(p.id, 'approve')}
              >
                ✅ Одобрить
              </Button>
              <Button
                type="button"
                disabled={busy !== null}
                onClick={() => decide(p.id, 'reject')}
              >
                ❌ Отклонить
              </Button>
              <Button
                type="button"
                disabled={busy !== null}
                onClick={() => {
                  form.reset();
                  setRevisionId(p.id);
                }}
              >
                ✏️ Доработать
              </Button>
            </div>
          )}
        </Card>
      ))}
      {posts?.length === 0 && (
        <Card className="card muted">Постов пока нет.</Card>
      )}
    </div>
  );
}
