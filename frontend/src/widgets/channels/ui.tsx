import { ConfirmAction, Button, Card, Input, Label, FormErrors } from "@/shared/ui";
import { useState } from 'react';
import { api, channelSchema } from '@/entities/marketing';
import { useLoad, useEditorForm } from '@/shared/lib';

export function Channels({ id }: { id: number }) {
  const [list, reload, loadError] = useLoad(() => api.socials(id), [id]);
  const form = useEditorForm(channelSchema, { channel: '' });
  const ch = form.values.channel;
  const [err, setErr] = useState('');
  const submit = async (values: typeof form.values) => {
    try {
      await api.addSocial(id, values.channel);
      form.reset();
      setErr('');
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="split">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <form onSubmit={form.handleSubmit(submit)}>
        <Card className="card">
          <h3>Подключить канал Telegram</h3>
          <Label>
            @username или ID канала
            <Input
              placeholder="@channel или -100…"
              {...form.register('channel')}
              aria-invalid={!!form.formState.errors.channel}
            />
          </Label>
          <p className="muted">
            Бот должен быть администратором канала с правом публикации.
          </p>
          <FormErrors errors={form.formState.errors} />
          {err && <div className="error">{err}</div>}
          <Button
            type="submit"
            variant="default"
            disabled={form.formState.isSubmitting || !ch}
          >
            Подключить
          </Button>
        </Card>
      </form>
      <div>
        {(list ?? []).map((s) => (
          <Card className="card" key={s.id}>
            <div className="cardHead">
              <b>{s.channel_id}</b>
              <span className={`dot ${s.active ? 'ok' : 'off'}`} />
            </div>
            <span className="muted">
              {s.platform} · {s.active ? 'активен' : 'доступ отозван'}
            </span>
            {s.active && (
              <div className="row">
                <ConfirmAction
                  description={`Отозвать доступ к каналу ${s.channel_id}?`}
                  onConfirm={async () => {
                    await api.revokeSocial(s.id);
                    reload();
                  }}
                >
                  Отозвать доступ
                </ConfirmAction>
              </div>
            )}
          </Card>
        ))}
        {list?.length === 0 && <Card className="card muted">Каналов нет.</Card>}
        <Card className="card muted">VK и MAX — в разработке.</Card>
      </div>
    </div>
  );
}
