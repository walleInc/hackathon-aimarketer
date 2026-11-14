import { test, expect, type Page } from '@playwright/test';

async function mockApi(page: Page, role: 'member' | 'approver' = 'member') {
  const company = {id: 1, name: 'Компания', description: '', brand_style: '', brand_rules: '', brand_colors: '', daily_post_limit: 5, monthly_token_limit: 300000};
  let plan: any = null;
  let nextItem = 10;
  const posts: any[] = [];
  const writes: {path: string; method: string; body: any}[] = [];
  await page.route('https://telegram.org/**', (route) => route.fulfill({body: '', contentType: 'application/javascript'}));
  await page.route('**/api/**', async (route) => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname; const method = req.method();
    if (!path.startsWith('/api/')) { await route.continue(); return; }
    const body = req.postDataJSON();
    if (method !== 'GET') writes.push({path, method, body});
    let json: any = [];
    if (path === '/api/me') json = {role, name: 'Маркетолог', company, telegram_id: 101};
    else if (path === '/api/agent/messages') json = {items: [], next_cursor: null};
    else if (path === '/api/agent/runs') json = [];
    else if (path === '/api/admin/companies') json = [company];
    else if (path === '/api/content-plans' && method === 'POST') {
      plan = {id: 1, ...body, status: 'ready', completed_days: 2, total_days: 2, created_by: 101,
        days: [{date: '2030-01-01', status: 'done', error: ''}, {date: '2030-01-02', status: 'done', error: ''}],
        items: [
          {id: 1, plan_id: 1, planned_date: '2030-01-01', title: 'Полезный совет', description: 'Расскажите о продукте', position: 0, version: 1, posts: []},
          {id: 2, plan_id: 1, planned_date: '2030-01-02', title: 'История бренда', description: 'Подготовьте историю компании', position: 0, version: 1, posts: []},
        ]}; json = {id: 1};
    } else if (path === '/api/content-plans') json = plan ? [plan] : [];
    else if (path === '/api/content-plans/1') json = plan;
    else if (path === '/api/content-plans/1/items') {
      const item = {id: nextItem++, plan_id: 1, ...body, version: 1, posts: []}; plan.items.push(item); json = item;
    } else if (path.startsWith('/api/content-plans/items/')) {
      const id = Number(path.split('/').pop());
      if (method === 'DELETE') { plan.items = plan.items.filter((i: any) => i.id !== id); json = {ok: true}; }
      else { const item = plan.items.find((i: any) => i.id === id); Object.assign(item, body, {version: item.version + 1}); json = item; }
    } else if (path === '/api/posts/generate') {
      const post = {id: posts.length + 1, platform: 'telegram', text: `Готовый пост: ${body.prompt}`, image_url: '', status: 'pending_approval', version: 1, scheduled_at: null, created_at: '2030-01-01T09:00:00', error: ''};
      posts.push(post); if (body.content_plan_item_id) plan.items.find((i: any) => i.id === body.content_plan_item_id).posts.push({id: post.id, status: post.status}); json = post;
    } else if (path === '/api/posts' || path.endsWith('/posts')) json = posts;
    else if (/^\/api\/posts\/\d+$/.test(path)) json = posts.find((p) => p.id === Number(path.split('/').pop()));
    else if (path.endsWith('/files')) json = {enabled: true, files: []};
    await route.fulfill({json});
  });
  return writes;
}

async function createPlan(page: Page) {
  await page.getByRole('tab', {name: 'Профиль', exact: true}).click();
  await page.getByLabel('Название плана').fill('План на январь');
  await page.getByLabel('Начало периода').fill('2030-01-01');
  await page.getByLabel('Конец периода').fill('2030-01-02');
  await page.getByLabel('Постов в день').fill('1');
  await page.getByLabel('Пожелания к плану').fill('Продвижение продукта');
  await page.getByRole('button', {name: 'Сгенерировать план', exact: true}).click();
  await expect(page.getByText('Готов · Дней готово: 2 из 2')).toBeVisible();
}

for (const role of ['member', 'approver'] as const) {
  test(`${role} generates a shared plan in profile and edits daily tasks on mobile`, async ({page}) => {
    const writes = await mockApi(page, role);
    await page.setViewportSize({width: 390, height: 844});
    await page.goto('/'); await createPlan(page);
    await expect(page.getByRole('heading', {name: 'Маркетолог', exact: true})).toBeVisible();
    const item = page.locator('.plan-item').filter({has: page.getByRole('heading', {name: 'Полезный совет', exact: true})});
    await item.getByRole('button', {name: 'Изменить задачу'}).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Дата задачи').fill('2030-01-02');
    await dialog.getByLabel('Тема задачи').fill('Новая тема');
    await dialog.getByLabel('Описание задачи').fill('Новое описание задания');
    await dialog.getByRole('button', {name: 'Сохранить задачу'}).click();
    await expect(page.getByRole('heading', {name: 'Новая тема', exact: true})).toBeVisible();
    expect(writes.find((w) => w.method === 'PATCH')?.body).toMatchObject({version: 1, planned_date: '2030-01-02', title: 'Новая тема'});
    await page.getByRole('button', {name: 'Добавить задачу', exact: true}).first().click();
    await dialog.getByLabel('Тема задачи').fill('Дополнительная тема');
    await dialog.getByLabel('Описание задачи').fill('Ручное задание');
    await dialog.getByRole('button', {name: 'Сохранить задачу'}).click();
    const added = page.locator('.plan-item').filter({has: page.getByRole('heading', {name: 'Дополнительная тема', exact: true})});
    await added.getByRole('button', {name: 'Удалить задачу Дополнительная тема'}).click();
    await expect(dialog).toContainText('Уже созданные посты сохранятся');
    await dialog.getByRole('button', {name: 'Подтвердить', exact: true}).click();
    await expect(page.getByRole('heading', {name: 'Дополнительная тема', exact: true})).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path: `test-results/content-plan-${role}-mobile.png`, fullPage: true});
  });
}

test('plan task fills editable post assignment; template can be reused and posts survive deletion', async ({page}) => {
  const writes = await mockApi(page);
  await page.goto('/'); await createPlan(page);
  const item = page.locator('.plan-item').filter({has: page.getByRole('heading', {name: 'Полезный совет', exact: true})});
  await item.getByRole('button', {name: 'Создать пост по задаче'}).click();
  await expect(page.getByLabel('Задание для поста')).toHaveValue('Полезный совет\nРасскажите о продукте');
  await page.getByLabel('Задание для поста').fill('Уточнённое задание');
  await page.getByRole('button', {name: 'Сгенерировать пост', exact: true}).click();
  await expect(page.getByText('Готовый пост: Уточнённое задание', {exact: true})).toBeVisible();
  expect(writes.at(-1)?.body).toEqual({prompt: 'Уточнённое задание', content_plan_item_id: 1});
  await page.getByRole('button', {name: 'Сгенерировать пост', exact: true}).click();
  await expect(item.getByRole('button', {name: /Пост #2/})).toBeVisible();
  await item.getByRole('button', {name: 'Удалить задачу Полезный совет', exact: true}).click();
  await page.getByRole('dialog').getByRole('button', {name: 'Подтвердить', exact: true}).click();
  await page.getByRole('tab', {name: 'Посты', exact: true}).click();
  await expect(page.getByText('Готовый пост: Уточнённое задание', {exact: true})).toHaveCount(2);
});

test('post creation offers plan/date/task selection and generation without template', async ({page}) => {
  const writes = await mockApi(page);
  await page.goto('/'); await createPlan(page);
  await page.getByRole('tab', {name: 'Посты', exact: true}).click();
  await page.getByRole('combobox', {name: 'Контент-план', exact: true}).selectOption('1');
  await page.getByLabel('Дата задачи').fill('2030-01-02');
  await page.getByRole('combobox', {name: 'Задача плана', exact: true}).selectOption('2');
  await expect(page.getByLabel('Задание для поста')).toHaveValue('История бренда\nПодготовьте историю компании');
  await page.getByRole('button', {name: 'Сгенерировать пост', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Сгенерировать пост', exact: true})).toBeEnabled();
  expect(writes.at(-1)?.body.content_plan_item_id).toBe(2);
  await page.getByRole('combobox', {name: 'Контент-план', exact: true}).selectOption('0');
  await page.getByLabel('Задание для поста').fill('Свободное задание');
  await page.getByRole('button', {name: 'Сгенерировать пост', exact: true}).click();
  await expect.poll(() => writes.filter((w) => w.path === '/api/posts/generate').length).toBe(2);
  expect(writes.at(-1)?.body).toEqual({prompt: 'Свободное задание'});
});
