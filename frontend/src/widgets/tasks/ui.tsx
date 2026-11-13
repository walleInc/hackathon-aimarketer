import { api, taskSchema, fmtDate } from "@/entities/marketing";
import { useLoad, useEditorForm } from '@/shared/lib';
import { Button, Card, Input, Textarea, Label, FormErrors } from '@/shared/ui';

export function Tasks({ id }: { id: number }) {
  const [tasks, reload, loadError] = useLoad(() => api.tasks(id), [id]);
  const form = useEditorForm(taskSchema, { prompt: '', hours: 24 });
  const { values: t, setValues: setT } = form;
  const submit = async (values: typeof t) => {
    try {
      await api.createTask(id, values.prompt, values.hours * 60);
      setT({ prompt: '', hours: 24 });
      reload();
    } catch (e) {
      form.setError('root', { message: (e as Error).message });
    }
  };
  const every = (min: number) =>
    min % 1440 === 0
      ? `каждые ${min / 1440} дн.`
      : min % 60 === 0
        ? `каждые ${min / 60} ч.`
        : `каждые ${min} мин.`;
  return (
    <form onSubmit={form.handleSubmit(submit)} className="contents">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <FormErrors errors={form.formState.errors} />
      <div className="split">
        <Card className="card">
          <h3>Регулярная задача</h3>
          <Label>
            Что делать
            <Textarea
              rows={3}
              placeholder="Подготовь пост про одну из позиций меню"
              {...form.register('prompt')}
              aria-invalid={!!form.formState.errors.prompt}
            />
          </Label>
          <Label>
            Периодичность, часов
            <Input
              type="number"
              min={1}
              {...form.register('hours', { valueAsNumber: true })}
              aria-invalid={!!form.formState.errors.hours}
            />
          </Label>
          <Button
            type="submit"
            variant="default"
            disabled={form.formState.isSubmitting || !t.prompt || t.hours < 1}
          >
            Создать
          </Button>
          <p className="muted">
            Агент сам готовит материал и отправляет на согласование.
          </p>
        </Card>
        <div>
          {(tasks ?? []).map((x) => (
            <Card className="card" key={x.id}>
              <div className="cardHead">
                <b>{every(x.interval_minutes)}</b>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await api.toggleTask(x.id, !x.active);
                      reload();
                    } catch (e) {
                      form.setError('root', { message: (e as Error).message });
                    }
                  }}
                >
                  {x.active ? 'Выключить' : 'Включить'}
                </Button>
              </div>
              <p>{x.prompt}</p>
              <span className="muted">
                Последний запуск: {fmtDate(x.last_run)} ·{' '}
                {x.active ? 'активна' : 'выключена'}
              </span>
            </Card>
          ))}
          {tasks?.length === 0 && (
            <Card className="card muted">Регулярных задач нет.</Card>
          )}
        </div>
      </div>
    </form>
  );
}
