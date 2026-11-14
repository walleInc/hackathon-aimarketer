import { test, expect, type Page } from '@playwright/test';

async function taskApi(page: Page, role = 'member') {
  let tasks: Record<string, unknown>[] = [];
  const writes: {method: string; path: string; body: any}[] = [];
  let next = 1;
  await page.route('https://telegram.org/**', (route) => route.fulfill({ body: '', contentType: 'application/javascript' }));
  await page.route('**/api/**', async (route) => {
    const req = route.request(); const path = new URL(req.url()).pathname;
    if (!path.startsWith('/api/')) { await route.continue(); return; }
    const method = req.method(); const body = req.postDataJSON();
    if (method !== 'GET') writes.push({ method, path, body });
    let json: unknown = [];
    if (path === '/api/me') json = {role, company: {id: 1, name: 'Компания'}, telegram_id: 101};
    else if (path === '/api/agent/messages') json = {items: [], next_cursor: null};
    else if (path === '/api/agent/runs') json = [];
    else if (path === '/api/tasks/catalog') json = [
      {id: 'post', name: 'Подготовка поста', description: 'Пост на согласование', requires: []},
      {id: 'market', name: 'Анализ рынка', description: 'Поиск со ссылками', requires: ['web_search']},
      {id: 'recommendations', name: 'Рекомендации по контенту', description: 'Темы', requires: []},
      {id: 'statistics', name: 'Сбор статистики сообщества', description: 'Метрики', requires: ['telegram']},
    ];
    else if (path === '/api/tasks' && method === 'POST') {
      const task = {id: next++, ...body, weekdays: body.weekdays.join(','), active: true, next_run: '2030-01-02T07:00:00', last_run: null};
      tasks.unshift(task); json = {id: task.id};
    } else if (path === '/api/tasks') json = tasks;
    else if (/\/api\/tasks\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop());
      if (method === 'DELETE') tasks = tasks.filter((t) => t.id !== id);
      if (method === 'PATCH') tasks = tasks.map((t) => t.id === id ? {...t, ...body} : t);
      json = {ok: true};
    } else if (path.endsWith('/runs')) json = [{id: 1, status: 'succeeded', scheduled_for: '2030-01-02T07:00:00', started_at: null, finished_at: null,
      result: 'Рост интереса к продукту', error: '', post_id: null, metrics: {views: 120}, sources: [{title: 'Исследование рынка', url: 'https://example.org/report'}]}];
    else if (path === '/api/telegram-analytics') json = {configured: true, connected: true, can_connect: role === 'approver', web_search_configured: true, channels: [{id: 3, channel_id: '@company'}]};
    else if (path === '/api/admin/companies') json = [{id: 1, name: 'Компания', description: '', brand_style: '', brand_rules: '', brand_colors: '', daily_post_limit: 5, monthly_token_limit: 300000}];
    await route.fulfill({json});
  });
  return writes;
}

test('employee creates each task type; calendar and interval payloads are correct on mobile', async ({page}) => {
  const writes = await taskApi(page);
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/');
  await expect(page.getByRole('heading', {name: 'Задачи', exact: true})).toBeVisible();
  for (const kind of ['post', 'market', 'recommendations', 'statistics']) {
    await page.getByLabel('Тип задачи').selectOption(kind);
    await page.getByLabel('Уточнение задачи').fill('  Продвижение продукта  ');
    await page.getByRole('combobox', {name: 'Расписание', exact: true}).selectOption('once');
    await page.getByLabel('Часовой пояс', {exact: true}).fill('Europe/Riga');
    await page.getByLabel(/Первая публикация|Первый запуск/).fill('2030-01-02T09:00');
    if (kind === 'statistics') await page.getByRole('combobox', {name: 'Telegram-канал', exact: true}).selectOption('3');
    await page.getByRole('button', {name: 'Создать задачу', exact: true}).click();
    await expect.poll(() => writes.filter((w) => w.path === '/api/tasks').length).toBe(['post', 'market', 'recommendations', 'statistics'].indexOf(kind) + 1);
    await expect(page.getByRole('button', {name: 'Создать задачу', exact: true})).toBeEnabled();
    expect(writes.at(-1)?.body).toMatchObject({kind, prompt: 'Продвижение продукта', schedule_kind: 'once', first_run_local: '2030-01-02T09:00', timezone: 'Europe/Riga'});
  }
  await page.getByRole('combobox', {name: 'Расписание', exact: true}).selectOption('weekly');
  await page.getByLabel('Вт', {exact: true}).check();
  await page.getByLabel('Пн', {exact: true}).uncheck();
  await page.getByLabel('Время публикации', {exact: true}).fill('12:30');
  await page.getByRole('button', {name: 'Создать задачу', exact: true}).click();
  await expect.poll(() => writes.length).toBe(5);
  expect(writes.at(-1)?.body).toMatchObject({schedule_kind: 'weekly', weekdays: [1], local_time: '12:30'});
  await page.getByRole('combobox', {name: 'Расписание', exact: true}).selectOption('interval');
  await page.getByLabel('Периодичность, часов').fill('6');
  await page.getByLabel(/Первая публикация/).fill('2030-01-02T09:00');
  await page.getByRole('button', {name: 'Создать задачу', exact: true}).click();
  await expect.poll(() => writes.length).toBe(6);
  expect(writes.at(-1)?.body.interval_minutes).toBe(360);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/tasks-mobile.png', fullPage: true});
});

test('results include sources and metrics; pause and deletion preserve prepared materials', async ({page}) => {
  const writes = await taskApi(page);
  await page.goto('/');
  await page.getByLabel('Тип задачи').selectOption('market');
  await page.getByRole('button', {name: 'Создать задачу', exact: true}).click();
  await page.getByRole('button', {name: 'История и результаты'}).click();
  await expect(page.getByText('Рост интереса к продукту')).toBeVisible();
  await expect(page.getByRole('link', {name: 'Исследование рынка'})).toHaveAttribute('href', 'https://example.org/report');
  await page.getByText('Исходные показатели').click();
  await expect(page.locator('pre')).toContainText('120');
  await page.getByRole('button', {name: 'Приостановить', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Включить', exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Удалить задачу', exact: true}).click();
  await expect(page.getByRole('dialog')).toContainText('назначенные публикации сохранятся');
  await page.getByRole('button', {name: 'Подтвердить', exact: true}).click();
  await expect(page.getByText('Задач по расписанию пока нет.')).toBeVisible();
  expect(writes.at(-1)?.method).toBe('DELETE');
});

test('company approver can complete Telegram login with 2FA', async ({page}) => {
  await taskApi(page, 'approver');
  let connected = false;
  await page.route('**/api/telegram-analytics', (route) => route.fulfill({json: {configured: true, connected, can_connect: true, web_search_configured: true, channels: []}}));
  await page.route('**/api/telegram-analytics/connect', (route) => route.fulfill({json: {step: 'code'}}));
  await page.route('**/api/telegram-analytics/verify', async (route) => {
    const body = route.request().postDataJSON();
    if (body.password) connected = true;
    await route.fulfill({json: {step: body.password ? 'connected' : 'password'}});
  });
  await page.goto('/');
  await page.getByRole('tab', {name: 'Задачи', exact: true}).click();
  await page.getByLabel('Номер телефона').fill('+37112345678');
  await page.getByRole('button', {name: 'Получить код'}).click();
  await page.getByLabel('Код из Telegram').fill('12345');
  await page.getByRole('button', {name: 'Подтвердить вход'}).click();
  await page.getByLabel('Пароль 2FA').fill('test-password');
  await page.getByRole('button', {name: 'Подтвердить вход'}).click();
  await expect(page.getByText('Аккаунт подключён', {exact: true})).toBeVisible();
  await expect(page.getByLabel('Пароль 2FA')).toHaveCount(0);
});

test('late approval offers a new publication time instead of publishing', async ({page}) => {
  const writes = await taskApi(page, 'approver');
  let post = {id: 9, platform: 'telegram', text: 'Пост по расписанию', image_url: '', status: 'pending_approval', version: 1,
    scheduled_at: '2020-01-01T09:00:00', needs_reschedule: false, error: '', created_at: '2020-01-01T08:00:00', check_notes: ''};
  await page.route('**/api/tasks/*/runs*', (route) => route.fulfill({json: [{id: 1, status: 'succeeded', scheduled_for: '2020-01-01T09:00:00', started_at: null, finished_at: null,
    result: 'Пост подготовлен', error: '', post_id: 9, sources: [], metrics: {}}]}));
  await page.route('**/api/posts/9', (route) => route.fulfill({json: post}));
  await page.route('**/api/posts/9/decision', async (route) => {
    post = {...post, status: 'approved', needs_reschedule: true}; await route.fulfill({json: post});
  });
  await page.route('**/api/posts/9/reschedule', async (route) => {
    const body = route.request().postDataJSON(); writes.push({method: 'POST', path: '/api/posts/9/reschedule', body});
    post = {...post, scheduled_at: body.scheduled_at, needs_reschedule: false, version: 2}; await route.fulfill({json: post});
  });
  await page.goto('/');
  await page.getByRole('tab', {name: 'Задачи', exact: true}).click();
  await page.getByRole('button', {name: 'Создать задачу', exact: true}).click();
  await page.getByRole('button', {name: 'История и результаты'}).click();
  await page.getByRole('button', {name: 'Открыть пост #9'}).click();
  await page.getByRole('button', {name: 'Одобрить пост', exact: true}).click();
  await expect(page.getByText('Время публикации прошло. Выберите новое время.', {exact: true})).toBeVisible();
  await page.getByLabel('Новое время публикации (часовой пояс устройства)').fill('2030-01-02T09:00');
  await page.getByRole('button', {name: 'Перенести публикацию', exact: true}).click();
  await expect(page.getByText('Время публикации прошло. Выберите новое время.', {exact: true})).toHaveCount(0);
  expect(writes.at(-1)?.body.version).toBe(1);
});
