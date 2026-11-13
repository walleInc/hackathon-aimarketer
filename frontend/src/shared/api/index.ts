declare global {
  interface Window {
    Telegram?: { WebApp?: { initData: string; ready(): void; expand(): void } };
  }
}

// Админ выбирает компанию, с которой работает; клиент всегда привязан к своей на сервере
let companyId: number | null = null;
export const setCompany = (id: number | null) => {
  companyId = id;
};

export function headers(
  extra: Record<string, string> = {},
): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  const initData = window.Telegram?.WebApp?.initData;
  if (initData) h['Authorization'] = `tma ${initData}`;
  else if (import.meta.env.VITE_DEV_USER)
    h['X-Dev-User'] = import.meta.env.VITE_DEV_USER; // только dev
  if (companyId) h['X-Company-Id'] = String(companyId);
  return { ...h, ...extra };
}

export async function req<T>(
  method: string,
  url: string,
  body?: unknown,
  extra: Record<string, string> = {},
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: headers(extra),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      typeof err.detail === 'string' ? err.detail : `HTTP ${res.status}`,
    );
  }
  return res.json();
}
