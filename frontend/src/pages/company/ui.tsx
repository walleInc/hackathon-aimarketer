import { Button, Tabs, TabsList, TabsTrigger, TabsContent } from '@/shared/ui';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';

import { Profile } from '@/widgets/profile';
import { Log } from '@/widgets/audit-log';
import { Posts } from '@/widgets/posts';
import { PostAnalytics } from '@/widgets/post-analytics';
import { Tasks } from '@/widgets/tasks';
import { Team } from '@/widgets/team';
import { Channels } from '@/widgets/channels';
import { BrandKit } from '@/widgets/brand-kit';
import { Knowledge } from '@/widgets/knowledge';
import { Overview } from '@/widgets/company-overview';
import { Marketer } from '@/widgets/marketer';
import { AgentChat } from '@/widgets/agent-chat';
const TABS = [
  'Обзор',
  'Маркетолог',
  'ИИ',
  'Профиль',
  'Знания',
  'Бренд',
  'Каналы',
  'Команда',
  'Задачи',
  'Посты',
  'Статистика',
  'Журнал',
] as const;
type TabName = (typeof TABS)[number];
export function CompanyPage({
  id,
  back,
  limitsEditable,
}: {
  id: number;
  back?: () => void;
  limitsEditable: boolean;
}) {
  const [tab, setTab] = useState<TabName>('Обзор');
  const navigation = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!window.matchMedia('(max-width: 720px)').matches) return;
    const list = navigation.current?.querySelector<HTMLElement>('[role="tablist"]');
    const active = list?.querySelector<HTMLElement>('[data-state="active"]');
    if (list && active) {
      list.scrollTo({ left: active.offsetLeft - (list.clientWidth - active.offsetWidth) / 2 });
    }
  }, [tab]);
  const [companies, reload, error] = useLoad(() => api.companies(), [id]);
  const company = companies?.find((c) => c.id === id);

  return (
    <>
      {back && (
        <div className="crumbs">
          <Button type="button" variant="link" onClick={back}>
            ← Все компании
          </Button>
        </div>
      )}
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      <h1>{company?.name ?? '…'}</h1>
      <Tabs className="company-tabs" value={tab} onValueChange={(value) => setTab(value as TabName)}>
        <div ref={navigation} className="company-navigation">
        <TabsList aria-label="Разделы компании" className="company-tabs-list flex h-auto w-full flex-wrap justify-start gap-1">
          {TABS.filter(t => t !== 'ИИ' || !limitsEditable).map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>
        </div>
        <TabsContent value="Обзор">
          {company && (
            <Overview
              saved={reload}
              company={company}
              go={setTab}
              limitsEditable={limitsEditable}
            />
          )}
        </TabsContent>
        <TabsContent value="ИИ"><AgentChat /></TabsContent>
        <TabsContent value="Профиль"><Profile id={id} /></TabsContent>
        <TabsContent value="Знания">
          <Knowledge id={id} />
        </TabsContent>
        <TabsContent value="Маркетолог">
          <Marketer id={id} />
        </TabsContent>
        <TabsContent value="Бренд">
          {company && <BrandKit saved={reload} company={company} />}
        </TabsContent>
        <TabsContent value="Каналы">
          <Channels id={id} />
        </TabsContent>
        <TabsContent value="Команда">
          <Team id={id} />
        </TabsContent>
        <TabsContent value="Задачи">
          <Tasks id={id} />
        </TabsContent>
        <TabsContent value="Посты">
          <Posts id={id} canDecide={!limitsEditable} />
        </TabsContent>
        <TabsContent value="Статистика">
          <PostAnalytics id={id} canEdit={!limitsEditable} />
        </TabsContent>
        <TabsContent value="Журнал">
          <Log id={id} />
        </TabsContent>
      </Tabs>
    </>
  );
}
