import { api } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';
import { Card } from '@/shared/ui';
import { ContentPlans } from '@/widgets/content-plans';

export function Profile({id}: {id: number}) {
  const [me, , error] = useLoad(api.me, []);
  return <div className="space-y-4"><h2>Профиль</h2>
    {error && <p role="alert" className="error">{error}</p>}
    {me && <Card className="card"><h3>{me.name || `Пользователь ${me.telegram_id}`}</h3>
      <p>Telegram ID: {me.telegram_id}</p><p>Роль: {me.role === 'member' ? 'Сотрудник' : me.role === 'approver' ? 'Администратор компании' : 'Оператор сервиса'}</p>
      {me.company && <p>Компания: {me.company.name}</p>}
    </Card>}
    {me && <ContentPlans id={id} canEdit={me.role === 'member' || me.role === 'approver'} />}
  </div>;
}
