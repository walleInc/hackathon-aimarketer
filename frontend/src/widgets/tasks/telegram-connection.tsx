import { useState, type FormEvent } from 'react';
import { api, type TelegramAnalytics } from '@/entities/marketing';
import { Button, Card, Input, Label, ConfirmAction } from '@/shared/ui';

export function TelegramConnection({ state, reload }: { state: TelegramAnalytics; reload: () => void }) {
  const [step, setStep] = useState('phone');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [channels, setChannels] = useState<{channel_id: string; title: string}[]>([]);
  const [channel, setChannel] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const result = step === 'phone' ? await api.connectTelegram(phone) : await api.verifyTelegram(code, password);
      setStep(result.step); setCode(''); setPassword('');
      if (result.step === 'connected') reload();
    } catch (e) { setError((e as Error).message); setCode(''); setPassword(''); }
    finally { setBusy(false); }
  };
  return <Card className="card space-y-3">
    <h3>Статистика Telegram</h3>
    <p>{state.connected ? 'Аккаунт подключён' : 'Аккаунт не подключён'}</p>
    {!state.configured && <p className="muted">Для подключения оператор задаёт TELEGRAM_API_ID и TELEGRAM_API_HASH на сервере.</p>}
    {!state.can_connect && !state.connected && <p className="muted">Подключение выполняет администратор компании.</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {state.can_connect && state.configured && !state.connected && <form onSubmit={submit} className="space-y-3">
      <p className="muted">Подключите аккаунт с доступом к каналу. Сессия хранится зашифрованной. Код и пароль 2FA не сохраняются.</p>
      {step === 'phone' ? <Label>Номер телефона<Input type="tel" autoComplete="tel" placeholder="+371…" pattern="\+[1-9][0-9]{6,14}" value={phone} onChange={(e) => setPhone(e.target.value)} required /></Label> :
        step === 'password' ? <Label>Пароль 2FA<Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} required /></Label> :
        <Label>Код из Telegram<Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required /></Label>}
      <div className="row"><Button disabled={busy}>{step === 'phone' ? 'Получить код' : 'Подтвердить вход'}</Button>
        {step !== 'phone' && <Button type="button" variant="outline" disabled={busy} onClick={() => { setStep('phone'); setCode(''); setPassword(''); }}>Запросить новый код</Button>}</div>
    </form>}
    {state.can_connect && state.connected && <>
      <Button variant="outline" disabled={busy} onClick={async () => {
        setBusy(true); setError('');
        try { setChannels(await api.availableChannels()); } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
      }}>Выбрать канал аккаунта</Button>
      {channels.length > 0 && <form className="space-y-3" onSubmit={async (event) => {
        event.preventDefault(); setBusy(true); setError('');
        try { await api.attachAnalyticsChannel(channel); setChannels([]); setChannel(''); reload(); }
        catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}><Label>Канал<select className="task-select" required value={channel} onChange={(e) => setChannel(e.target.value)}>
        <option value="">Выберите канал</option>{channels.map((c) => <option key={c.channel_id} value={c.channel_id}>{c.title}</option>)}
      </select></Label><Button disabled={busy || !channel}>Добавить канал для статистики</Button></form>}
      <ConfirmAction description="Сессия Telegram будет отозвана. Задачи статистики сохранятся, но для новых запусков потребуется подключить аккаунт." onConfirm={async () => { await api.disconnectTelegram(); setStep('phone'); reload(); }}>Отключить аккаунт</ConfirmAction>
    </>}
  </Card>;
}
