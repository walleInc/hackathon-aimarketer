import { test, expect, type Page } from '@playwright/test';

async function chatApi(page: Page, role = 'member', initiallyRunning = false) {
  const state = { started: initiallyRunning, done: false, rejectNext: false, writes: [] as any[] };
  const run = () => ({ id: 7, kind: 'message', prompt: 'Новая задача', status: state.done ? 'completed' : 'running',
    result: state.done ? 'Готово. Результат задачи.' : '', error: '', image_url: '', post_id: state.done ? 9 : null,
    parent_run_id: 3, created_at: '2026-11-14T00:00:00' });
  const base = [
    { id: 10, role: 'user', content: 'Вчерашняя задача', run_id: 3, post_id: null, image_url: '', created_at: '2026-11-13T23:59:00' },
    { id: 11, role: 'assistant', content: 'Вчера подготовили материал.', run_id: 3, post_id: 9, image_url: '', created_at: '2026-11-13T23:59:30' },
  ];
  await page.route('https://telegram.org/**', route => route.fulfill({ body: '' }));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    let result: unknown = [];
    if (url.pathname === '/api/me') result = { role, telegram_id: 101, company: { id: 1, name: 'Компания' } };
    else if (url.pathname === '/api/agent/runs' && request.method() === 'POST') {
      state.writes.push(request.postDataJSON());
      if (state.rejectNext) {
        state.rejectNext = false;
        await route.fulfill({ status: 503, json: { detail: 'Сервис временно недоступен' } });
        return;
      }
      state.started = true;
      result = { ...run(), status: 'queued' };
    } else if (url.pathname === '/api/agent/runs') result = state.started ? [run()] : [];
    else if (url.pathname === '/api/agent/messages') {
      result = url.searchParams.has('before') ? { items: [
        { id: 1, role: 'user', content: 'Переписка месяц назад', run_id: 1, post_id: null, image_url: '', created_at: '2026-10-14T12:00:00' },
      ], next_cursor: null } : { items: [...base, ...(state.started ? [
        { id: 12, role: 'user', content: 'Новая задача', run_id: 7, post_id: null, image_url: '', created_at: '2026-11-14T00:00:00' },
      ] : []), ...(state.done ? [
        { id: 13, role: 'assistant', content: 'Готово. Результат задачи.', run_id: 7, post_id: 9, image_url: '', created_at: '2026-11-14T00:00:10' },
      ] : [])], next_cursor: 10 };
    } else if (url.pathname === '/api/posts/9') result = { id: 9, text: 'Текст материала', status: 'pending_approval', image_url: '', version: 1 };
    else if (url.pathname.endsWith('/companies')) result = [{ id: 1, name: 'Компания', description: '', brand_style: '', brand_rules: '', brand_colors: '' }];
    await route.fulfill({ json: result });
  });
  return state;
}

test('personal history, older messages and linked follow-up survive reload', async ({ page }) => {
  const state = await chatApi(page);
  await page.goto('/');
  await expect(page.getByRole('log')).toContainText('Вчера подготовили материал.');
  await expect(page.getByRole('log')).toContainText('UTC');
  await page.getByRole('button', { name: 'Предыдущие сообщения' }).click();
  await expect(page.getByRole('log')).toContainText('Переписка месяц назад');
  await page.getByRole('button', { name: 'Уточнить результат #3' }).click();
  await page.getByLabel('Задача или вопрос', { exact: true }).fill('Почему выбрали этот текст?');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  expect(state.writes[0]).toEqual({ text: 'Почему выбрали этот текст?', parent_run_id: 3 });
  await expect(page.getByRole('status')).toContainText('выполняется');
  state.done = true;
  await expect(page.getByRole('log')).toContainText('Готово. Результат задачи.', { timeout: 7000 });
  await expect(page.getByRole('log')).toContainText('Переписка месяц назад');
  await page.reload();
  await expect(page.getByRole('log')).toContainText('Готово. Результат задачи.');
  await page.getByRole('button', { name: 'Открыть материал #9' }).last().click();
  await expect(page.getByRole('dialog')).toContainText('Текст материала');
  await expect(page.getByRole('dialog')).toContainText('На согласовании');
});

test('running job is restored on mobile and completion appears once', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await chatApi(page, 'member', true);
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('Задача #7');
  await page.reload();
  await expect(page.getByRole('status')).toContainText('выполняется');
  state.done = true;
  await expect(page.getByText('Готово. Результат задачи.', { exact: true })).toHaveCount(1, { timeout: 7000 });
  await expect(page.getByRole('status')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('company administrator has AI tab and failed submission preserves question', async ({ page }) => {
  const state = await chatApi(page, 'approver');
  await page.goto('/');
  await page.getByRole('tab', { name: 'ИИ', exact: true }).click();
  await page.getByLabel('Задача или вопрос', { exact: true }).fill('Поясни результат');
  state.rejectNext = true;
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Сервис временно недоступен');
  await expect(page.getByLabel('Задача или вопрос', { exact: true })).toHaveValue('Поясни результат');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Задача #7');
});
