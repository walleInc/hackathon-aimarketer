import { z } from 'zod';
const required = z.string().trim().min(1, 'Заполните поле');
export const companySchema = z.object({
  name: required,
  description: z.string(),
  brand_style: z.string(),
});
export const profileSchema = companySchema.extend({
  daily_post_limit: z.number().int().min(1, 'Минимум 1 материал'),
  monthly_token_limit: z.number().int().min(1000, 'Минимум 1000 токенов'),
});
export const knowledgeSchema = z.object({ title: required, content: required });
export const brandSchema = z.object({
  brand_rules: z.string(),
  brand_colors: z
    .string()
    .refine(
      (v) =>
        !v.trim() ||
        v.split(',').every((c) => /^#[0-9a-f]{6}$/i.test(c.trim())),
      'Введите HEX-цвета через запятую',
    ),
});
export const channelSchema = z.object({
  channel: z
    .string()
    .trim()
    .regex(
      /^(@[a-zA-Z0-9_]{5,}|-100\d+)$/,
      'Укажите @username или ID вида -100…',
    ),
});
export const taskSchema = z.object({
  prompt: required,
  hours: z
    .number()
    .int()
    .min(1, 'Минимум 1 час')
    .max(8760, 'Максимум 8760 часов'),
});

export const revisionSchema = z.object({
  comment: z.string().trim().min(1, 'Опишите необходимые изменения'),
});
