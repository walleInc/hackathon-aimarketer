import { ConfirmAction, Button, Card, Input, Textarea, Label, FormErrors } from "@/shared/ui";
import { useState } from 'react';
import { api, knowledgeSchema, fmtDate } from "@/entities/marketing";
import { useLoad, useEditorForm } from '@/shared/lib';

import { ContextFiles } from './context-files';
export function Knowledge({ id }: { id: number }) {
  const [docs, reload, loadError] = useLoad(() => api.knowledge(id), [id]);
  // editing = null (создание нового) или id редактируемого документа
  const [editing, setEditing] = useState<number | null>(null);
  const form = useEditorForm(knowledgeSchema, { title: '', content: '' });
  const { values: d, setValues: setD } = form;
  const [err, setErr] = useState('');

  const startEdit = (x: { id: number; title: string; content: string }) => {
    setEditing(x.id);
    setD({ title: x.title, content: x.content });
    setErr('');
  };
  const reset = () => {
    setEditing(null);
    setD({ title: '', content: '' });
    setErr('');
  };
  const save = async (values: typeof d) => {
    try {
      if (editing === null)
        await api.addKnowledge(id, values.title, values.content);
      else await api.updateKnowledge(editing, values.title, values.content);
      reset();
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <form onSubmit={form.handleSubmit(save)} className="contents">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <FormErrors errors={form.formState.errors} />
      <div className="split">
        <Card className="card">
          <h3>
            {editing === null ? 'Добавить знания' : 'Редактирование документа'}
          </h3>
          <Label>
            Название
            <Input
              placeholder="О компании, Продукты, Конкуренты…"
              {...form.register('title')}
              aria-invalid={!!form.formState.errors.title}
            />
          </Label>
          <Label>
            Текст
            <Textarea
              rows={10}
              {...form.register('content')}
              aria-invalid={!!form.formState.errors.content}
            />
          </Label>
          {err && <div className="error">{err}</div>}
          <div className="row">
            <Button
              variant="default"
              type="submit"
              disabled={form.formState.isSubmitting || !d.title || !d.content}
            >
              {editing === null ? 'Добавить' : 'Сохранить изменения'}
            </Button>
            {editing !== null && (
              <Button type="button" onClick={reset}>
                Отмена
              </Button>
            )}
          </div>
          {editing !== null && (
            <p className="muted">
              Агент начнёт использовать обновлённый текст со следующего запроса.
            </p>
          )}
        </Card>
        <div>
          {(docs ?? []).map((x) => (
            <Card
              className={`card ${editing === x.id ? 'active' : ''}`}
              key={x.id}
            >
              <div className="cardHead">
                <b>{x.title}</b>
                <span>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => startEdit(x)}
                  >
                    Изменить
                  </Button>
                  <ConfirmAction
                    description={`Удалить документ «${x.title}»?`}
                    onConfirm={async () => {
                      await api.deleteKnowledge(x.id);
                      if (editing === x.id) reset();
                      reload();
                    }}
                  >
                    Удалить
                  </ConfirmAction>
                </span>
              </div>
              <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{x.content}</p>
              <span className="muted">
                {x.size} симв.
                {x.updated_at ? ` · изменён ${fmtDate(x.updated_at)}` : ''}
              </span>
            </Card>
          ))}
          {docs?.length === 0 && (
            <Card className="card muted">
              База знаний пуста. Агент не сможет опираться на факты о компании.
            </Card>
          )}
          <ContextFiles id={id} />
        </div>
      </div>
    </form>
  );
}
