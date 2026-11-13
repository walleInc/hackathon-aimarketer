import { useState } from 'react';
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
  Textarea,
  FormErrors,
} from '@/shared/ui';

export function Posts({ id, canDecide }: { id: number; canDecide: boolean }) {
  const [posts, reload, loadError] = useLoad(() => api.companyPosts(id), [id]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState<number | null>(null);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const form = useEditorForm(revisionSchema, { comment: '' });
  const decide = async (
    pid: number,
    decision: 'approve' | 'reject' | 'revise',
    comment = '',
  ) => {
    setBusy(pid);
    setErr('');
    try {
      await api.decide(pid, decision, comment);
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
      {err && <Card className="card error">{err}</Card>}
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
