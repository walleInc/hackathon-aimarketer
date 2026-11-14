import { Profile } from '@/widgets/profile';
import { Posts } from '@/widgets/posts';
import { Card, Tabs, TabsList, TabsTrigger, TabsContent } from '@/shared/ui';
import { useEffect, useState } from 'react';
import { api, type Me } from '@/entities/marketing';
import { Admin } from './admin-layout';
import { Tasks } from '@/widgets/tasks';
import { Marketer } from '@/widgets/marketer';
import { AgentChat } from '@/widgets/agent-chat';

/** Mini App: кабинет компании и личный профиль с общими планами, задачами и постами. */
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
    return <div className="app wide"><header className="top"><div className="brand">AI маркетолог · {me.company.name}</div></header>
      <AgentChat /><Tabs defaultValue="tasks"><TabsList aria-label="Рабочие разделы"><TabsTrigger value="marketing">Маркетолог</TabsTrigger><TabsTrigger value="tasks">Задачи</TabsTrigger><TabsTrigger value="profile">Профиль</TabsTrigger><TabsTrigger value="posts">Посты</TabsTrigger></TabsList>
        <TabsContent value="marketing"><Marketer id={me.company.id} /></TabsContent><TabsContent value="tasks"><h1>Задачи</h1><Tasks id={me.company.id} /></TabsContent>
        <TabsContent value="profile"><Profile id={me.company.id} /></TabsContent>
        <TabsContent value="posts"><h1>Посты</h1><Posts id={me.company.id} canDecide={false} employee /></TabsContent>
      </Tabs></div>;
  }

  return (
    <div className="app narrow">
      <header className="top">
        <div className="brand">
          <span className="logo">AI</span> маркетолог
        </div>
      </header>
      {me.company ? <AgentChat /> : <Card className="card">Для доступа к компании нужна ссылка-приглашение.</Card>}
    </div>
  );
}
