import { Button, Tabs, TabsList, TabsTrigger, TabsContent } from '@/shared/ui';
import { useState } from 'react';
import { api } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';

import { Log } from '@/widgets/audit-log';
import { Posts } from '@/widgets/posts';
import { Tasks } from '@/widgets/tasks';
import { Team } from '@/widgets/team';
import { Channels } from '@/widgets/channels';
import { BrandKit } from '@/widgets/brand-kit';
import { Knowledge } from '@/widgets/knowledge';
import { Overview } from '@/widgets/company-overview';
const TABS = [
  'Обзор',
  'Знания',
  'Бренд',
  'Каналы',
  'Команда',
  'Задачи',
  'Посты',
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
      <Tabs value={tab} onValueChange={(value) => setTab(value as TabName)}>
        <TabsList className="flex h-auto w-full justify-start overflow-x-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>
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
        <TabsContent value="Знания">
          <Knowledge id={id} />
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
        <TabsContent value="Журнал">
          <Log id={id} />
        </TabsContent>
      </Tabs>
    </>
  );
}
