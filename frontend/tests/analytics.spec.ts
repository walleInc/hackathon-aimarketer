import { test, expect, type Page } from '@playwright/test';

async function mockAnalytics(page: Page, role = 'approver', empty = false) {
  const writes: { path: string; body: any }[] = [];
  const metric = (value: number | null) => ({ value, observed_at: value === null ? null : '2026-11-14T09:00:00+00:00', source: value === null ? '' : 'manual' });
  const posts = empty ? [] : [1, 2, 3].map((id) => ({
    id, text: `Пример публикации ${id}`, platform: 'telegram', channel_id: '-100123', external_id: String(id),
    published_at: '2026-11-12T09:00:00+00:00', has_image: true,
    metrics: { views: metric(100), reactions: metric(id), forwards: metric(null), comments: metric(null) }, reaction_rate: id,
  }));
  const data = {
    period_days: 30, published_posts: posts.length, sample_size: posts.length, max_posts: 200, unknown_publication_dates: 0,
    summary: { views: { total: empty ? null : 300, measured_posts: posts.length }, reactions: { total: empty ? null : 6, measured_posts: posts.length },
      forwards: { total: null, measured_posts: 0 }, comments: { total: null, measured_posts: 0 }, reaction_rate: empty ? null : 2, rate_posts: posts.length },
    posts, daily_publications: empty ? [] : [{ date: '2026-11-12', posts: 3 }],
    recommendations: [{ title: 'Проверьте подачу поста #3 ещё раз', text: 'Это гипотеза на основе измерений.', post_ids: [3] }],
    ai_advice: null as null | { text: string; created_at: string; stale: boolean },
  };
  await page.route('https://telegram.org/**', (route) => route.fulfill({ body: '', contentType: 'application/javascript' }));
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) { await route.continue(); return; }
    let result: unknown = [];
    if (path === '/api/me') result = { telegram_id: 100, role, company: role === 'approver' ? { id: 1, name: 'Компания' } : null };
    else if (path === '/api/admin/companies') result = [{ id: 1, name: 'Компания', description: '', brand_style: '', brand_rules: '', brand_colors: '', daily_post_limit: 5, monthly_token_limit: 300000 }];
    else if (path === '/api/admin/stats') result = [{ id: 1, name: 'Компания', posts: {}, users: 1, channels: 1, tokens: 0, cost_usd: 0, month_tokens: 0, monthly_token_limit: 300000 }];
    else if (path === '/api/analytics/posts') result = data;
    else if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON() });
      if (path.endsWith('/metrics')) {
        const body = request.postDataJSON();
        if (posts[0] && body.views !== undefined) posts[0].metrics.views = metric(body.views);
        if (data.ai_advice) data.ai_advice.stale = true;
        result = { ok: true };
      } else if (path.endsWith('/recommendations')) {
        data.ai_advice = { text: 'Гипотеза: повторить подачу поста #3 на новой теме.', created_at: '2026-11-14T10:00:00+00:00', stale: false };
        result = data.ai_advice;
      }
    }
    await route.fulfill({ json: result });
  });
  return writes;
}

test('metrics editor preserves unknowns, validates input and AI report becomes stale', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const writes = await mockAnalytics(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Статистика', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Статистика публикаций' })).toBeVisible();
  await expect(page.getByText('Измерено 0 из 3 постов')).toHaveCount(2);
  await page.getByRole('button', { name: 'Получить AI-рекомендации', exact: true }).click();
  await expect(page.getByText('Гипотеза: повторить подачу поста #3 на новой теме.')).toBeVisible();
  expect(writes[0]).toEqual({ path: '/api/analytics/posts/recommendations', body: { days: 30 } });
  await page.getByRole('button', { name: 'Внести показатели поста #1', exact: true }).click();
  await page.getByRole('button', { name: 'Сохранить показатели', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Заполните хотя бы один показатель');
  expect(writes).toHaveLength(1);
  await page.getByLabel('Просмотры', { exact: true }).fill('-1');
  await page.getByRole('button', { name: 'Сохранить показатели', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Введите целое число');
  await page.getByLabel('Просмотры', { exact: true }).fill('0');
  await page.getByRole('button', { name: 'Сохранить показатели', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  expect(writes[1]).toEqual({ path: '/api/posts/1/metrics', body: { views: 0 } });
  await expect(page.getByText('Показатели изменились.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/analytics-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('empty analytics disables AI; service operator has read-only analytics', async ({ page }) => {
  await mockAnalytics(page, 'approver', true);
  await page.goto('/');
  await page.getByRole('tab', { name: 'Статистика', exact: true }).click();
  await expect(page.getByText('За выбранный период опубликованных постов нет.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Получить AI-рекомендации', exact: true })).toBeDisabled();
  await page.unroute('**/api/**');
  await mockAnalytics(page, 'admin');
  await page.reload();
  await page.getByRole('button', { name: /Компания/ }).click();
  await page.getByRole('tab', { name: 'Статистика', exact: true }).click();
  await expect(page.getByText('Пример публикации 1')).toBeVisible();
  await expect(page.getByRole('button', { name: /Внести показатели/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Получить AI-рекомендации', exact: true })).toHaveCount(0);
});
