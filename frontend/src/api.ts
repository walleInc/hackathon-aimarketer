declare global {
  interface Window {
    Telegram?: { WebApp?: { initData: string; ready(): void; expand(): void } };
  }
}

export type Post = {
  id: number; platform: string; text: string; image_url: string; status: string;
  version: number; scheduled_at: string | null; error: string; created_at: string; check_notes?: string;
};
export type Me = { telegram_id: number; role: string; company: { id: number; name: string } | null };
export type Company = {
  id: number; name: string; description: string; brand_style: string; brand_rules: string; brand_colors: string;
  daily_post_limit: number; monthly_token_limit: number;
};
export type Asset = { id: number; kind: string; filename: string; url: string };
export type Stat = {
  id: number; name: string; posts: Record<string, number>; users: number; channels: number; tokens: number;
  cost_usd: number; month_tokens: number; monthly_token_limit: number;
};
export type ContextFile = { name: string; size: number; modified: string; supported: boolean };
export type Doc = { id: number; title: string; content: string; size: number; updated_at: string | null };
export type Social = { id: number; platform: string; channel_id: string; active: boolean };
export type Member = { id: number; telegram_id: number; name: string; role: string };
export type TaskItem = { id: number; prompt: string; interval_minutes: number; active: boolean; last_run: string | null };
export type Operator = { telegram_id: number; name: string; company_id: number | null; source: "env" | "db"; you: boolean };
export type AuditItem = { id: number; company_id: number | null; action: string; details: string; created_at: string };

// Админ выбирает компанию, с которой работает; клиент всегда привязан к своей на сервере
let companyId: number | null = null;
export const setCompany = (id: number | null) => { companyId = id; };

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const initData = window.Telegram?.WebApp?.initData;
  if (initData) h["Authorization"] = `tma ${initData}`;
  else if (import.meta.env.VITE_DEV_USER) h["X-Dev-User"] = import.meta.env.VITE_DEV_USER; // только dev
  if (companyId) h["X-Company-Id"] = String(companyId);
  return { ...h, ...extra };
}

async function req<T>(method: string, url: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const res = await fetch(url, { method, headers: headers(extra), body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`);
  }
  return res.json();
}

const A = "/api/admin";

export const api = {
  me: () => req<Me>("GET", "/api/me"),
  posts: (status?: string) => req<Post[]>("GET", `/api/posts${status ? `?status=${status}` : ""}`),
  decide: (id: number, decision: "approve" | "reject" | "revise", comment = "") =>
    req<Post>("POST", `/api/posts/${id}/decision`, { decision, comment }),
  chat: (text: string) => req<{ reply: string; post_id: number | null }>("POST", "/api/agent/message", { text }),

  stats: () => req<Stat[]>("GET", `${A}/stats`),
  companies: () => req<Company[]>("GET", `${A}/companies`),
  createCompany: (c: Partial<Omit<Company, "id">> & { name: string }) => req<{ id: number }>("POST", `${A}/companies`, c),
  updateCompany: (id: number, c: Partial<Omit<Company, "id">>) => req("PUT", `${A}/companies/${id}`, c),
  updateKnowledge: (docId: number, title: string, content: string) => req("PUT", `${A}/knowledge/${docId}`, { title, content }),
  assets: (id: number) => req<Asset[]>("GET", `${A}/companies/${id}/assets`),
  deleteAsset: (assetId: number) => req("DELETE", `${A}/assets/${assetId}`),
  uploadAsset: async (id: number, kind: string, file: File) => {
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    const h = headers(); delete h["Content-Type"]; // boundary проставит браузер
    const res = await fetch(`${A}/companies/${id}/assets`, { method: "POST", headers: h, body: fd });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
    return res.json();
  },
  preview: (id: number, headline: string, body: string, style: "dark" | "light") =>
    req<{ url: string }>("POST", `${A}/companies/${id}/brand/preview`, { headline, body, style }),
  invite: (id: number, role: string) => req<{ code: string }>("POST", `${A}/companies/${id}/invite`, { role }),
  knowledge: (id: number) => req<Doc[]>("GET", `${A}/companies/${id}/knowledge`),
  addKnowledge: (id: number, title: string, content: string) =>
    req("POST", `${A}/companies/${id}/knowledge`, { title, content }),
  deleteKnowledge: (docId: number) => req("DELETE", `${A}/knowledge/${docId}`),
  contextFiles: (id: number) => req<{ enabled: boolean; files: ContextFile[] }>("GET", `${A}/companies/${id}/files`),
  deleteContextFile: (id: number, name: string) => req("DELETE", `${A}/companies/${id}/files/${encodeURIComponent(name)}`),
  uploadContextFile: async (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const h = headers(); delete h["Content-Type"];
    const res = await fetch(`${A}/companies/${id}/files`, { method: "POST", headers: h, body: fd });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
    return res.json();
  },
  socials: (id: number) => req<Social[]>("GET", `${A}/companies/${id}/social`),
  addSocial: (id: number, channel_id: string) =>
    req("POST", `${A}/companies/${id}/social`, { platform: "telegram", channel_id }),
  revokeSocial: (accountId: number) => req("DELETE", `${A}/social/${accountId}`),
  members: (id: number) => req<Member[]>("GET", `${A}/companies/${id}/users`),
  companyPosts: (id: number) => req<Post[]>("GET", `${A}/companies/${id}/posts`),
  tasks: (id: number) => req<TaskItem[]>("GET", `${A}/companies/${id}/tasks`),
  toggleTask: (taskId: number, active: boolean) => req("PATCH", `${A}/tasks/${taskId}`, { active }),
  createTask: (id: number, prompt: string, interval_minutes: number) =>
    req("POST", "/api/tasks", { prompt, interval_minutes }, { "X-Company-Id": String(id) }),
  operators: () => req<Operator[]>("GET", `${A}/operators`),
  addOperator: (telegram_id: number, name: string) => req("POST", `${A}/operators`, { telegram_id, name }),
  removeOperator: (telegram_id: number) => req("DELETE", `${A}/operators/${telegram_id}`),
  audit: (id?: number) => req<AuditItem[]>("GET", `${A}/audit${id ? `?company_id=${id}` : ""}`),
};
