import { req } from '@/shared/api';
import type { Competitor, HypothesisStatus, MarketingKind, MarketingProfile, MarketingState } from './model/workspace';
const root = '/api/marketing';
const scope = (id: number) => ({ 'X-Company-Id': String(id) });
export const workspaceApi = {
  state: (id: number, days: number, channel: string) => req<MarketingState>('GET', `${root}/state?days=${days}&channel=${encodeURIComponent(channel)}`, undefined, scope(id)),
  profile: (id: number, profile: MarketingProfile) => req('PUT', `${root}/profile`, profile, scope(id)),
  addCompetitor: (id: number, value: Omit<Competitor, 'id' | 'confirmed'>) => req('POST', `${root}/competitors`, value, scope(id)),
  confirmCompetitor: (id: number, item: number) => req('POST', `${root}/competitors/${item}/confirm`, undefined, scope(id)),
  deleteCompetitor: (id: number, item: number) => req('DELETE', `${root}/competitors/${item}`, undefined, scope(id)),
  start: (id: number, kind: MarketingKind, days: number, channel: string, prompt = '', channel_id?: number) =>
    req<{ run_id: number }>('POST', `${root}/jobs`, { kind, days, channel, prompt, channel_id }, scope(id)),
  hypothesis: (id: number, item: number, status: HypothesisStatus, result: string) => req('PATCH', `${root}/hypotheses/${item}`, { status, result }, scope(id)),
  approve: (id: number, document: number) => req('POST', `${root}/documents/${document}/approve`, undefined, scope(id)),
  prepare: (id: number, type: 'plan' | 'hypotheses', item: number) => req<{ run_id: number }>('POST', `${root}/${type}/${item}/prepare`, undefined, scope(id)),
  schedule: (id: number, active: boolean, timezone: string, local_time: string) => req('PUT', `${root}/report-schedule`, { active, timezone, local_time }, scope(id)),
};
