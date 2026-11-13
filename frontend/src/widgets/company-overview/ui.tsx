import { useState } from 'react';
import { api, type Company, profileSchema } from '@/entities/marketing';
import { useLoad, useEditorForm } from '@/shared/lib';
import { Button, Card, Input, Textarea, Label, FormErrors } from '@/shared/ui';

type TabName =
  | 'Обзор'
  | 'Знания'
  | 'Бренд'
  | 'Каналы'
  | 'Команда'
  | 'Задачи'
  | 'Посты'
  | 'Журнал';
export function Overview({
  company,
  go,
  limitsEditable,
  saved,
}: {
  company: Company;
  saved: () => void;
  go: (t: TabName) => void;
  limitsEditable: boolean;
}) {
  const form = useEditorForm(profileSchema, {
    name: company.name,
    description: company.description,
    brand_style: company.brand_style,
    daily_post_limit: company.daily_post_limit,
    monthly_token_limit: company.monthly_token_limit,
  });
  const { values: f } = form;
  const [msg, setMsg] = useState('');
  const [docs] = useLoad(() => api.knowledge(company.id), [company.id]);
  const [socials] = useLoad(() => api.socials(company.id), [company.id]);
  const [members] = useLoad(() => api.members(company.id), [company.id]);
  const steps: [string, boolean, TabName][] = [
    ['Загружены знания о компании', (docs?.length ?? 0) > 0, 'Знания'],
    [
      'Подключён канал для публикаций',
      (socials ?? []).some((s) => s.active),
      'Каналы',
    ],
    [
      'Есть администратор компании (согласующий)',
      (members ?? []).some((m) => m.role === 'approver'),
      'Команда',
    ],
  ];
  const save = async (values: typeof f) => {
    try {
      const { daily_post_limit, monthly_token_limit, ...profile } = values;
      await api.updateCompany(company.id, limitsEditable ? values : profile);
      saved();
      setMsg('Сохранено');
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <form onSubmit={form.handleSubmit(save)} className="contents">
      <FormErrors errors={form.formState.errors} />
      <div className="split">
        <Card className="card">
          <h3>Профиль и бренд</h3>
          <Label>
            Название
            <Input
              {...form.register('name')}
              aria-invalid={!!form.formState.errors.name}
            />
          </Label>
          <Label>
            Чем занимается
            <Textarea
              rows={3}
              {...form.register('description')}
              aria-invalid={!!form.formState.errors.description}
            />
          </Label>
          <Label>
            Тон и стиль общения
            <Textarea
              rows={3}
              {...form.register('brand_style')}
              aria-invalid={!!form.formState.errors.brand_style}
            />
          </Label>
          <h3 style={{ marginTop: 16 }}>Лимиты</h3>
          <div className="row2">
            <Label>
              Материалов в сутки
              <Input
                type="number"
                min={1}
                readOnly={!limitsEditable}
                {...form.register('daily_post_limit', { valueAsNumber: true })}
                aria-invalid={!!form.formState.errors.daily_post_limit}
              />
            </Label>
            <Label>
              Токенов AI в месяц
              <Input
                type="number"
                min={1000}
                step={1000}
                readOnly={!limitsEditable}
                {...form.register('monthly_token_limit', {
                  valueAsNumber: true,
                })}
                aria-invalid={!!form.formState.errors.monthly_token_limit}
              />
            </Label>
          </div>
          <p className="muted">
            При превышении агент останавливается и уведомляет администратора —
            расходы не выходят за рамки.
          </p>
          <div className="row">
            <Button
              variant="default"
              type="submit"
              disabled={form.formState.isSubmitting}
            >
              Сохранить
            </Button>
            <span className="muted">{msg}</span>
          </div>
        </Card>
        <Card className="card">
          <h3>Готовность к работе</h3>
          {steps.map(([label, ok, tab]) => (
            <div key={label} className="check" onClick={() => go(tab)}>
              <span className={`dot ${ok ? 'ok' : 'warn'}`} />{' '}
              <span>{label}</span>
              <span className="muted">{ok ? 'готово' : 'настроить →'}</span>
            </div>
          ))}
        </Card>
      </div>
    </form>
  );
}
