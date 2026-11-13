import { req, headers } from '@/shared/api';
import type {
  Post,
  Me,
  Company,
  Asset,
  Stat,
  ContextFile,
  Doc,
  Social,
  Member,
  TaskItem,
  AuditItem,
} from './model/types';
const A = '/api/admin';

export const api = {
  me: () => req<Me>('GET', '/api/me'),
  posts: (status?: string) =>
    req<Post[]>('GET', `/api/posts${status ? `?status=${status}` : ''}`),
  decide: (
    id: number,
    decision: 'approve' | 'reject' | 'revise',
    comment = '',
  ) => req<Post>('POST', `/api/posts/${id}/decision`, { decision, comment }),
  chat: (text: string) =>
    req<{ reply: string; post_id: number | null }>(
      'POST',
      '/api/agent/message',
      { text },
    ),

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
  tasks: (id: number) => req<TaskItem[]>('GET', `${A}/companies/${id}/tasks`),
  toggleTask: (taskId: number, active: boolean) =>
    req('PATCH', `${A}/tasks/${taskId}`, { active }),
  createTask: (id: number, prompt: string, interval_minutes: number) =>
    req(
      'POST',
      '/api/tasks',
      { prompt, interval_minutes },
      { 'X-Company-Id': String(id) },
    ),
  audit: (id?: number) =>
    req<AuditItem[]>('GET', `${A}/audit${id ? `?company_id=${id}` : ''}`),
};
