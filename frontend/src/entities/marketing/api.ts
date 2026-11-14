import { req, headers } from '@/shared/api';
import type {
  Post, ContentPlan, ContentPlanInput, ContentPlanItemInput, ContentPlanItem,
  PostAnalytics,
  AnalyticsAdvice,
  MetricName,
  Me,
  Company,
  Asset,
  Stat,
  ContextFile,
  Doc,
  Social,
  Member,
  TaskItem, TaskInput, TaskCatalogItem, TaskRun, TelegramAnalytics,
  AuditItem,
} from './model/types';
const A = '/api/admin';

export const api = {
  contentPlans: (cid: number) => req<ContentPlan[]>('GET', '/api/content-plans', undefined, {'X-Company-Id': String(cid)}),
  contentPlan: (cid: number, id: number) => req<ContentPlan>('GET', `/api/content-plans/${id}`, undefined, {'X-Company-Id': String(cid)}),
  createContentPlan: (body: ContentPlanInput) => req<{id: number}>('POST', '/api/content-plans', body),
  retryContentPlan: (id: number) => req('POST', `/api/content-plans/${id}/retry`),
  addContentPlanItem: (id: number, body: ContentPlanItemInput) => req<ContentPlanItem>('POST', `/api/content-plans/${id}/items`, body),
  editContentPlanItem: (id: number, body: ContentPlanItemInput & {version: number}) => req<ContentPlanItem>('PATCH', `/api/content-plans/items/${id}`, body),
  deleteContentPlanItem: (id: number, version: number) => req('DELETE', `/api/content-plans/items/${id}?version=${version}`),
  generatePost: (prompt: string, content_plan_item_id?: number) => req<Post>('POST', '/api/posts/generate', {prompt, content_plan_item_id}),
  me: () => req<Me>('GET', '/api/me'),
  posts: (status?: string) =>
    req<Post[]>('GET', `/api/posts${status ? `?status=${status}` : ''}`),
  decide: (
    id: number,
    decision: 'approve' | 'reject' | 'revise',
    comment = '',
    version?: number,
  ) => req<Post>('POST', `/api/posts/${id}/decision`, { decision, comment, version }),
  editPost: (id: number, text: string, version: number) =>
    req<Post>('PATCH', `/api/posts/${id}`, { text, version }),
  regeneratePostImage: (id: number, prompt: string, version: number) =>
    req<Post>('POST', `/api/posts/${id}/image/regenerate`, { prompt, version }),
  uploadPostImage: async (id: number, file: File, version: number): Promise<Post> => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('version', String(version));
    const h = headers();
    delete h['Content-Type'];
    const res = await fetch(`/api/posts/${id}/image`, { method: 'POST', headers: h, body: fd });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${res.status}`);
    }
    return res.json();
  },
  chatWithReference: async (text: string, reference: File) => {
    const fd = new FormData();
    fd.append('text', text);
    fd.append('reference', reference);
    const h = headers();
    delete h['Content-Type'];
    const res = await fetch('/api/agent/message/reference', { method: 'POST', headers: h, body: fd });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ reply: string; post_id: number | null }>;
  },
  chat: (text: string) =>
    req<{ reply: string; post_id: number | null }>(
      'POST',
      '/api/agent/message',
      { text },
    ),

  postAnalytics: (id: number, days: number) =>
    req<PostAnalytics>('GET', `/api/analytics/posts?days=${days}`, undefined, { 'X-Company-Id': String(id) }),
  savePostMetrics: (id: number, values: Partial<Record<MetricName, number>>) =>
    req<{ ok: boolean }>('PUT', `/api/posts/${id}/metrics`, values),
  recommendPosts: (id: number, days: number) =>
    req<AnalyticsAdvice>('POST', '/api/analytics/posts/recommendations', { days }, { 'X-Company-Id': String(id) }),
  stats: () => req<Stat[]>('GET', `${A}/stats`),
  companies: () => req<Company[]>('GET', `${A}/companies`),
  createCompany: (c: Partial<Omit<Company, 'id'>> & { name: string }) =>
    req<{ id: number }>('POST', `${A}/companies`, c),
  updateCompany: (id: number, c: Partial<Omit<Company, 'id'>>) =>
    req('PUT', `${A}/companies/${id}`, c),
  updateKnowledge: (docId: number, title: string, content: string) =>
    req('PUT', `${A}/knowledge/${docId}`, { title, content }),
  assets: (id: number) => req<Asset[]>('GET', `${A}/companies/${id}/assets`),
  deleteAsset: (assetId: number) => req('DELETE', `${A}/assets/${assetId}`),
  uploadAsset: async (id: number, kind: string, file: File) => {
    const fd = new FormData();
    fd.append('kind', kind);
    fd.append('file', file);
    const h = headers();
    delete h['Content-Type']; // boundary проставит браузер
    const res = await fetch(`${A}/companies/${id}/assets`, {
      method: 'POST',
      headers: h,
      body: fd,
    });
    if (!res.ok)
      throw new Error(
        (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`,
      );
    return res.json();
  },
  preview: (
    id: number,
    headline: string,
    body: string,
    style: 'dark' | 'light',
  ) =>
    req<{ url: string }>('POST', `${A}/companies/${id}/brand/preview`, {
      headline,
      body,
      style,
    }),
  invite: (id: number, role: string) =>
    req<{ code: string }>('POST', `${A}/companies/${id}/invite`, { role }),
  knowledge: (id: number) =>
    req<Doc[]>('GET', `${A}/companies/${id}/knowledge`),
  addKnowledge: (id: number, title: string, content: string) =>
    req('POST', `${A}/companies/${id}/knowledge`, { title, content }),
  deleteKnowledge: (docId: number) => req('DELETE', `${A}/knowledge/${docId}`),
  contextFiles: (id: number) =>
    req<{ enabled: boolean; files: ContextFile[] }>(
      'GET',
      `${A}/companies/${id}/files`,
    ),
  deleteContextFile: (id: number, name: string) =>
    req('DELETE', `${A}/companies/${id}/files/${encodeURIComponent(name)}`),
  uploadContextFile: async (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    const h = headers();
    delete h['Content-Type'];
    const res = await fetch(`${A}/companies/${id}/files`, {
      method: 'POST',
      headers: h,
      body: fd,
    });
    if (!res.ok)
      throw new Error(
        (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`,
      );
    return res.json();
  },
  socials: (id: number) => req<Social[]>('GET', `${A}/companies/${id}/social`),
  addSocial: (id: number, channel_id: string) =>
    req('POST', `${A}/companies/${id}/social`, {
      platform: 'telegram',
      channel_id,
    }),
  revokeSocial: (accountId: number) =>
    req('DELETE', `${A}/social/${accountId}`),
  setRole: (cid: number, userId: number, role: string) =>
    req('PATCH', `${A}/companies/${cid}/users/${userId}`, { role }),
  removeMember: (cid: number, userId: number) =>
    req('DELETE', `${A}/companies/${cid}/users/${userId}`),
  members: (id: number) => req<Member[]>('GET', `${A}/companies/${id}/users`),
  companyPosts: (id: number) =>
    req<Post[]>('GET', `${A}/companies/${id}/posts`),
  taskCatalog: () => req<TaskCatalogItem[]>('GET', '/api/tasks/catalog'),
  tasks: (id: number) => req<TaskItem[]>('GET', '/api/tasks', undefined, { 'X-Company-Id': String(id) }),
  toggleTask: (taskId: number, active: boolean) => req('PATCH', `/api/tasks/${taskId}`, { active }),
  deleteTask: (taskId: number) => req('DELETE', `/api/tasks/${taskId}`),
  createTask: (id: number, body: TaskInput) => req('POST', '/api/tasks', body, { 'X-Company-Id': String(id) }),
  taskRuns: (taskId: number, before?: number) => req<TaskRun[]>('GET', `/api/tasks/${taskId}/runs${before ? `?before=${before}` : ''}`),
  taskPost: (postId: number, companyId: number) => req<Post>('GET', `/api/posts/${postId}`, undefined, { 'X-Company-Id': String(companyId) }),
  reschedulePost: (id: number, scheduled_at: string, version: number) => req<Post>('POST', `/api/posts/${id}/reschedule`, { scheduled_at, version }),
  telegramAnalytics: (id: number) => req<TelegramAnalytics>('GET', '/api/telegram-analytics', undefined, { 'X-Company-Id': String(id) }),
  connectTelegram: (phone: string) => req<{step: string}>('POST', '/api/telegram-analytics/connect', { phone }),
  verifyTelegram: (code: string, password: string) => req<{step: string}>('POST', '/api/telegram-analytics/verify', { code, password }),
  disconnectTelegram: () => req('DELETE', '/api/telegram-analytics'),
  availableChannels: () => req<{channel_id: string; title: string}[]>('GET', '/api/telegram-analytics/available-channels'),
  attachAnalyticsChannel: (channel_id: string) => req('POST', '/api/telegram-analytics/channels', { channel_id }),
  audit: (id?: number) =>
    req<AuditItem[]>('GET', `${A}/audit${id ? `?company_id=${id}` : ''}`),
};
