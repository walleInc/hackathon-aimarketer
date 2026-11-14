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
export const channelSchema = z
  .object({
    platform: z.enum(['telegram', 'vk']),
    channel: z.string().trim().min(1, 'Заполните поле'),
    token: z.string().trim(),
  })
  .superRefine((values, ctx) => {
    if (values.platform === 'telegram') {
      if (!/^(@[a-zA-Z0-9_]{5,}|-100\d+)$/.test(values.channel)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['channel'],
          message: 'Укажите @username или ID вида -100…',
        });
      }
      return;
    }
    if (
      !/^(-?\d+|club\d+|public\d+|(https?:\/\/)?(vk\.com\/)?[a-zA-Z0-9_.]{4,32})\/?$/.test(
        values.channel,
      )
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['channel'],
        message: 'Укажите ID сообщества, короткое имя или ссылку vk.com/…',
      });
    }
  });

export const revisionSchema = z.object({
  comment: z.string().trim().min(1, 'Опишите необходимые изменения'),
});


const metricInput = z.string().trim().refine(
  (value) => value === '' || (/^\d+$/.test(value) && Number(value) <= 2_000_000_000),
  'Введите целое число от 0 до 2 млрд',
);
export const postMetricsSchema = z.object({
  views: metricInput, reactions: metricInput, forwards: metricInput, comments: metricInput,
}).refine((values) => Object.values(values).some((value) => value !== ''), {
  message: 'Заполните хотя бы один показатель', path: ['views'],
});
