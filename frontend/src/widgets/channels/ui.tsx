import { ConfirmAction, Button, Card, Input, Label, FormErrors } from "@/shared/ui";
import { useState } from 'react';
import { api, channelSchema, PLATFORM_RU } from '@/entities/marketing';
import { useLoad, useEditorForm } from '@/shared/lib';

export function Channels({ id }: { id: number }) {
  const [list, reload, loadError] = useLoad(() => api.socials(id), [id]);
  const form = useEditorForm(channelSchema, {
    platform: 'telegram',
    channel: '',
    token: '',
  });
  const { platform, channel: ch } = form.values;
  const vk = platform === 'vk';
  const [err, setErr] = useState('');
  const submit = async (values: typeof form.values) => {
    try {
      await api.addSocial(id, {
        platform: values.platform,
        channel_id: values.channel,
        token: values.token,
      });
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
          <h3>Подключить площадку</h3>
          <Label>
            Площадка
            <select
              className="task-select"
              value={platform}
              onChange={(e) =>
                form.setValue('platform', e.target.value as 'telegram' | 'vk')
              }
            >
              <option value="telegram">Telegram</option>
              <option value="vk">ВКонтакте</option>
            </select>
          </Label>
          <Label>
            {vk ? 'Сообщество ВКонтакте' : '@username или ID канала'}
            <Input
              placeholder={vk ? 'vk.com/mybrand или -123456789' : '@channel или -100…'}
              {...form.register('channel')}
              aria-invalid={!!form.formState.errors.channel}
            />
          </Label>
          {vk && (
            <Label>
              Ключ доступа сообщества
              <Input
                type="password"
                autoComplete="off"
                placeholder="vk1.a…"
                {...form.register('token')}
              />
            </Label>
          )}
          <p className="muted">
            {vk
              ? 'Ключ создаётся в сообществе: Управление → Работа с API → Создать ключ с правами «Записи на стене» и «Фотографии». Если ключ задан на сервере (VK_ACCESS_TOKEN), поле можно оставить пустым.'
              : 'Бот должен быть администратором канала с правом публикации.'}
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
              {PLATFORM_RU[s.platform] ?? s.platform} ·{' '}
              {s.active ? 'активен' : 'доступ отозван'}
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
      </div>
    </div>
  );
}
