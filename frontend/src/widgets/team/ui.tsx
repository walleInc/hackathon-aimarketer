import { Badge, ConfirmAction, Button, Card } from '@/shared/ui';

import { useState } from 'react';
import { api } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';

export function Team({ id }: { id: number }) {
  const [members, reload, loadError] = useLoad(() => api.members(id), [id]);
  const [code, setCode] = useState('');
  const [err, setErr] = useState('');
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setErr('');
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const invite = async (role: string) => {
    try {
      setCode((await api.invite(id, role)).code);
      setErr('');
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const ROLE: Record<string, string> = {
    approver: 'Администратор компании',
    member: 'Сотрудник',
    admin: 'Тех. аккаунт',
  };
  return (
    <div className="split">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <Card className="card">
        <h3>Пригласить в компанию</h3>
        <div className="row">
          <Button
            type="button"
            variant="default"
            onClick={() => invite('approver')}
          >
            Администратор компании
          </Button>
          <Button type="button" onClick={() => invite('member')}>
            Сотрудник
          </Button>
        </div>
        {code && (
          <p>
            Отправьте ссылку (одноразовая):
            <br />
            <code>https://t.me/aimarketologgbot?start={code}</code>
          </p>
        )}
        <p className="muted">
          Администратор компании согласует публикации в чате бота и сам
          приглашает сотрудников командой /invite. Сотрудник ставит задачи в
          чате.
        </p>
      </Card>
      <div>
        {(members ?? []).map((m) => (
          <Card className="card" key={m.id}>
            <div className="cardHead">
              <b>{m.name || `ID ${m.telegram_id}`}</b>
              <Badge variant="secondary">{ROLE[m.role] ?? m.role}</Badge>
            </div>
            <span className="muted">Telegram ID {m.telegram_id}</span>
            {m.role !== 'admin' && (
              <div className="row">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    act(() =>
                      api.setRole(
                        id,
                        m.id,
                        m.role === 'approver' ? 'member' : 'approver',
                      ),
                    )
                  }
                >
                  {m.role === 'approver'
                    ? 'Сделать сотрудником'
                    : 'Сделать администратором компании'}
                </Button>
                <ConfirmAction
                  description="Отозвать доступ? Человек потеряет связь с компанией."
                  onConfirm={async () => {
                    await api.removeMember(id, m.id);
                    reload();
                  }}
                >
                  Удалить из компании
                </ConfirmAction>
              </div>
            )}
          </Card>
        ))}
        {err && <Card className="card error">{err}</Card>}
        {members?.length === 0 && (
          <Card className="card muted">В команде пока никого.</Card>
        )}
      </div>
    </div>
  );
}
