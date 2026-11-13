import { useState } from 'react';
import { api, companySchema } from '@/entities/marketing';
import { useEditorForm } from '@/shared/lib';
import { Button, Card, Input, Textarea, Label, FormErrors } from '@/shared/ui';

export function NewCompany({ done }: { done: (id: number) => void }) {
  const form = useEditorForm(companySchema, {
    name: '',
    description: '',
    brand_style: '',
  });
  const { values: f } = form;
  const [err, setErr] = useState('');
  const submit = async (values: typeof f) => {
    try {
      done((await api.createCompany(values)).id);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <form onSubmit={form.handleSubmit(submit)} className="contents">
      <FormErrors errors={form.formState.errors} />
      <Card className="card">
        <h3>Новая компания</h3>
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
            rows={2}
            {...form.register('description')}
            aria-invalid={!!form.formState.errors.description}
          />
        </Label>
        <Label>
          Стиль и требования бренда
          <Textarea
            rows={2}
            {...form.register('brand_style')}
            aria-invalid={!!form.formState.errors.brand_style}
          />
        </Label>
        {err && <div className="error">{err}</div>}
        <Button
          variant="default"
          type="submit"
          disabled={form.formState.isSubmitting || !f.name.trim()}
        >
          Создать
        </Button>
      </Card>
    </form>
  );
}
