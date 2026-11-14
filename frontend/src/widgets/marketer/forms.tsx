import { useEffect } from 'react';
import { z } from 'zod';
import { useEditorForm } from '@/shared/lib';
import { Button, Input, Textarea, Label, FormErrors } from '@/shared/ui';
import type { MarketingProfile } from '@/entities/marketing';

const profileSchema = z.object({ niche: z.string().max(500), geography: z.string().max(300), goals: z.string().max(4000) });
export function ProfileForm({ value, save, busy }: { value: MarketingProfile; save: (v: MarketingProfile) => Promise<void>; busy: boolean }) {
  const form = useEditorForm(profileSchema, value);
  useEffect(() => { form.reset(value); }, [value.niche, value.geography, value.goals]);
  return <form onSubmit={form.handleSubmit(async (v) => { try { await save(v); } catch { /* workspace renders the error */ } })} className="space-y-3"><fieldset disabled={busy}>
    <Label>Ниша и продукт<Input {...form.register('niche')} placeholder="Например, листовое стекло для строительства" /></Label>
    <Label>География рынка<Input {...form.register('geography')} placeholder="Страна, регион или город" /></Label>
    <Label>Маркетинговые цели<Textarea {...form.register('goals')} placeholder="Каких результатов хотим достичь" rows={3} /></Label>
    <FormErrors errors={form.formState.errors} /><Button type="submit">Сохранить контекст</Button>
  </fieldset></form>;
}
const safeUrl = z.string().max(1000).refine((v) => !v || /^https?:\/\//i.test(v) && (() => { try { return !!new URL(v).hostname; } catch { return false; } })(), 'Укажите ссылку http:// или https://');
const competitorSchema = z.object({ name: z.string().trim().min(1, 'Укажите название').max(200), website: safeUrl, telegram: safeUrl, notes: z.string().max(2000) });
export function CompetitorForm({ save, busy }: { save: (v: z.infer<typeof competitorSchema>) => Promise<void>; busy: boolean }) {
  const form = useEditorForm(competitorSchema, { name: '', website: '', telegram: '', notes: '' });
  return <form className="space-y-3" onSubmit={form.handleSubmit(async (v) => { try { await save(v); form.reset(); } catch { /* keep values for retry */ } })}><fieldset disabled={busy}>
    <Label>Название конкурента<Input {...form.register('name')} /></Label>
    <Label>Сайт конкурента<Input {...form.register('website')} placeholder="https://…" inputMode="url" /></Label>
    <Label>Telegram конкурента<Input {...form.register('telegram')} placeholder="https://t.me/…" inputMode="url" /></Label>
    <Label>Заметки<Textarea {...form.register('notes')} rows={2} /></Label>
    <FormErrors errors={form.formState.errors} /><Button type="submit">Добавить конкурента</Button>
  </fieldset></form>;
}
