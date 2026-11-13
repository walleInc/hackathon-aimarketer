import { test, expect, type Page } from '@playwright/test';
async function mockApi(page: Page, role = 'admin') {
  let company = {
    id: 1,
    name: 'Тестовая компания',
    description: 'Описание',
    brand_style: 'Деловой',
    brand_rules: '',
    brand_colors: '#196C7F, #285055',
    daily_post_limit: 5,
    monthly_token_limit: 300000,
  };
  const writes: { path: string; body: any }[] = [];
  await page.route('https://telegram.org/**', (route) =>
    route.fulfill({ body: '', contentType: 'application/javascript' }),
  );
  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (!path.startsWith('/api/')) {
      await route.continue();
      return;
    }
    let result: unknown = [];
    if (req.method() !== 'GET') {
      const body = req.postDataJSON();
      writes.push({ path, body });
      if (req.method() === 'PUT' && path.endsWith('/companies/1'))
        company = { ...company, ...body };
      result = { ok: true, id: 1 };
    } else if (path === '/api/me')
      result = {
        telegram_id: 1,
        role,
        company: role === 'approver' ? { id: 1, name: company.name } : null,
      };
    else if (path.endsWith('/stats'))
      result = [
        {
          ...company,
          posts: {},
          users: 1,
          channels: 1,
          tokens: 0,
          cost_usd: 0,
          month_tokens: 0,
        },
      ];
    else if (path.endsWith('/companies')) result = [company];
    else if (path.endsWith('/knowledge'))
      result = [
        {
          id: 8,
          title: 'О компании',
          content: 'Информация',
          size: 10,
          updated_at: null,
        },
      ];
    else if (path.endsWith('/posts'))
      result = [
        {
          id: 9,
          platform: 'telegram',
          text: 'Материал',
          image_url: '',
          status: 'pending_approval',
          version: 1,
          scheduled_at: null,
          error: '',
          created_at: '2026-11-13T12:00:00',
        },
      ];
    else if (path.endsWith('/files')) result = { enabled: true, files: [] };
    await route.fulfill({ json: result });
  });
  return writes;
}
test('profile persists across tabs; all company sections open on mobile', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: /Тестовая компания/ }).click();
  const navigation = page.getByRole('tablist', { name: 'Разделы компании' });
  const dock = await navigation.evaluate((list) => {
    const rect = list.getBoundingClientRect();
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    return {
      inside: rect.left >= 0 && rect.right <= window.innerWidth,
      bottom: rect.bottom > window.innerHeight - 100 && rect.bottom <= window.innerHeight,
      scrolls: list.scrollWidth > list.clientWidth,
      singleRow: new Set(tabs.map((tab) => tab.getBoundingClientRect().top)).size === 1,
    };
  });
  expect(dock).toEqual({ inside: true, bottom: true, scrolls: true, singleRow: true });
  await page
    .getByLabel('Название', { exact: true })
    .fill('Обновлённая компания');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Обновлённая компания',
  );
  for (const tab of [
    'Знания',
    'Бренд',
    'Каналы',
    'Команда',
    'Задачи',
    'Посты',
    'Журнал',
    'Обзор',
  ])
    await page.getByRole('tab', { name: tab, exact: true }).click();
  await expect(page.getByLabel('Название', { exact: true })).toHaveValue(
    'Обновлённая компания',
  );
  expect(writes[0].body.name).toBe('Обновлённая компания');
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: 'test-results/company-mobile.png',
    fullPage: true,
  });
});
test('brand and task schemas block invalid data; task submits trimmed data', async ({
  page,
}) => {
  const writes = await mockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Тестовая компания/ }).click();
  await page.getByRole('tab', { name: 'Бренд', exact: true }).click();
  await page.getByLabel('HEX через запятую, основной первым').fill('invalid');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Введите HEX');
  expect(writes).toHaveLength(0);
  await page.getByRole('tab', { name: 'Задачи', exact: true }).click();
  await page.getByLabel('Что делать').fill('   ');
  await page.getByRole('button', { name: 'Создать', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Заполните поле');
  expect(writes).toHaveLength(0);
  await page.getByLabel('Что делать').fill('  Напиши пост  ');
  await page.getByRole('button', { name: 'Создать', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toEqual({
    prompt: 'Напиши пост',
    interval_minutes: 1440,
  });
});
test('company admin saves profile without sending limits', async ({ page }) => {
  const writes = await mockApi(page, 'approver');
  await page.goto('/');
  await page.getByLabel('Название', { exact: true }).fill('Клиент');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).not.toHaveProperty('daily_post_limit');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Клиент');
});

test('revision and deletion use validated library dialogs', async ({
  page,
}) => {
  const writes = await mockApi(page, 'approver');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Посты', exact: true }).click();
  await page.getByRole('button', { name: /Доработать/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Отправить на доработку' }).click();
  await expect(dialog.getByRole('alert')).toContainText(
    'Опишите необходимые изменения',
  );
  expect(writes).toHaveLength(0);
  await dialog.getByLabel('Комментарий').fill('  Добавь подробности  ');
  await dialog.getByRole('button', { name: 'Отправить на доработку' }).click();
  await expect(dialog).not.toBeVisible();
  expect(writes[0].body).toEqual({
    decision: 'revise',
    comment: 'Добавь подробности',
  });
  await page.getByRole('tab', { name: 'Знания', exact: true }).click();
  await page.getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(dialog).toContainText('Удалить документ');
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  expect(writes).toHaveLength(1);
  await page.getByRole('button', { name: 'Удалить', exact: true }).click();
  await dialog
    .getByRole('button', { name: 'Подтвердить', exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  expect(writes[1].path).toBe('/api/admin/knowledge/8');
});
