import { test, expect, type Page } from '@playwright/test';

async function openWorkspace(page: Page, manager = false) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('https://telegram.org/**', (r) => r.fulfill({ body: '', contentType: 'application/javascript' }));
  if (manager) await page.route('**/api/**', (route) => route.continue({ headers: { ...route.request().headers(), 'x-dev-user': '100' } }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Маркетолог', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Кабинет маркетолога' })).toBeVisible();
  await expect(page.getByText('Измерено 3 из 3 постов').first()).toBeVisible();
  return errors;
}
const section = (page: Page, name: string) => page.getByRole('navigation', { name: 'Разделы маркетолога' }).getByRole('button', { name, exact: true }).click();

test('employee uses real analytics, experiments and plan; materials still require approval', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = await openWorkspace(page);
  await expect(page.getByText('600', { exact: true })).toBeVisible();
  await expect(page.getByText('Нет данных', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сохранить контекст' })).toHaveCount(0);
  await section(page, 'Рынок');
  await expect(page.getByRole('button', { name: 'Запустить анализ рынка' })).toBeDisabled();
  await section(page, 'Конкуренты');
  await page.getByLabel('Название конкурента').fill('Тестовый конкурент');
  await page.getByLabel('Сайт конкурента').fill('javascript:alert(1)');
  await page.getByRole('button', { name: 'Добавить конкурента', exact: true }).click();
  await expect(page.getByText('Укажите ссылку http:// или https://')).toBeVisible();
  await page.getByLabel('Сайт конкурента').fill('https://example.org');
  await page.getByRole('button', { name: 'Добавить конкурента', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Тестовый конкурент' })).toBeVisible();
  await section(page, 'Гипотезы');
  await page.getByRole('button', { name: 'Сформировать гипотезы' }).click();
  await expect(page.getByRole('heading', { name: 'Проверить подачу с вопросом аудитории' })).toBeVisible();
  await page.getByLabel('Статус гипотезы').selectOption('insufficient');
  await page.getByLabel('Результат эксперимента').fill('Пока недостаточно сопоставимых измерений');
  await page.getByRole('button', { name: 'Сохранить результат' }).click();
  await expect(page.getByText('Гипотеза обновлена', { exact: true })).toBeVisible();
  await section(page, 'Стратегия и план');
  await page.getByRole('button', { name: 'Составить план на 7 дней' }).click();
  await expect(page.getByRole('heading', { name: 'Тема дня 1: полезный материал о компании' })).toBeVisible();
  await page.getByRole('button', { name: 'Подготовить материал', exact: true }).first().click();
  await expect(page.getByRole('button', { name: 'Передан в подготовку' })).toBeDisabled();
  await page.getByText(/История запусков ·/).click();
  await page.getByRole('button', { name: /Пост #/ }).first().click();
  await expect(page.getByText('Ожидает согласования администратора', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/marketer-mobile.png', fullPage: true });
  await page.reload();
  await page.getByRole('tab', { name: 'Маркетолог', exact: true }).click();
  await section(page, 'Гипотезы');
  await expect(page.getByLabel('Результат эксперимента')).toHaveValue('Пока недостаточно сопоставимых измерений');
  expect(errors).toEqual([]);
});

test('company manager approves strategy and configures Monday reports through real API', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors = await openWorkspace(page, true);
  await expect(page.getByRole('button', { name: 'Сохранить контекст' })).toBeVisible();
  await page.screenshot({ path: 'test-results/marketer-desktop.png', fullPage: true });
  await section(page, 'Стратегия и план');
  await page.getByRole('button', { name: 'Подготовить стратегию' }).click();
  await page.getByRole('button', { name: 'Утвердить стратегию' }).click();
  await expect(page.getByText('Стратегия утверждена', { exact: true })).toBeVisible();
  await section(page, 'Отчёты');
  await page.getByLabel('Часовой пояс отчётов').fill('Asia/Yekaterinburg');
  await page.getByRole('button', { name: 'Сохранить расписание' }).click();
  await expect(page.getByText('Включён · Asia/Yekaterinburg', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Сформировать отчёт' }).click();
  await expect(page.getByText('Зафиксированные показатели отчёта', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('tab', { name: 'Маркетолог', exact: true }).click();
  await section(page, 'Отчёты');
  await expect(page.getByLabel('Часовой пояс отчётов')).toHaveValue('Asia/Yekaterinburg');
  expect(errors).toEqual([]);
});
