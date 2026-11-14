import { Card } from '@/shared/ui';
import { useEffect, useState } from 'react';
import { api, type Me } from '@/entities/marketing';
import { Admin } from './admin-layout';
import { Tasks } from '@/widgets/tasks';

/** Mini App — кабинет: тех. администратор видит все компании, администратор компании — свою. Сотрудники работают в чате. */
export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch((e) => setError(e.message));
  }, []);

  if (error)
    return (
      <div className="app">
        <Card role="alert" className="card error">
          {error}
        </Card>
      </div>
    );
  if (!me)
    return (
      <div className="app">
        <Card className="card">Загрузка…</Card>
      </div>
    );

  if (me.role === 'admin') return <Admin ownerView />;
  if (me.role === 'approver' && me.company)
    return <Admin companyId={me.company.id} ownerView={false} />;

  if (me.role === 'member' && me.company) {
    return <div className="app wide"><header className="top"><div className="brand">AI маркетолог · {me.company.name}</div></header><h1>Задачи</h1><Tasks id={me.company.id} /></div>;
  }

  return (
    <div className="app narrow">
      <header className="top">
        <div className="brand">
          <span className="logo">AI</span> маркетолог
        </div>
      </header>
      <Card className="card">
        <h3>Работа — в чате с ботом</h3>
        <p>
          Ставьте задачи и согласовывайте материалы прямо в переписке с ботом.
          Кабинет нужен администратору компании.
        </p>
      </Card>
    </div>
  );
}
