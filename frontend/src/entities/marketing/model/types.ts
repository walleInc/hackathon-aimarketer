export type Post = {
  id: number;
  platform: string;
  text: string;
  image_url: string;
  status: string;
  version: number;
  scheduled_at: string | null;
  needs_reschedule?: boolean;
  error: string;
  created_at: string;
  check_notes?: string;
};
export type Me = {
  telegram_id: number;
  role: string;
  company: { id: number; name: string } | null;
};
export type Company = {
  id: number;
  name: string;
  description: string;
  brand_style: string;
  brand_rules: string;
  brand_colors: string;
  daily_post_limit: number;
  monthly_token_limit: number;
};
export type Asset = { id: number; kind: string; filename: string; url: string };
export type Stat = {
  id: number;
  name: string;
  posts: Record<string, number>;
  users: number;
  channels: number;
  tokens: number;
  cost_usd: number;
  month_tokens: number;
  monthly_token_limit: number;
};
export type ContextFile = {
  name: string;
  size: number;
  modified: string;
  supported: boolean;
};
export type Doc = {
  id: number;
  title: string;
  content: string;
  size: number;
  updated_at: string | null;
};
export type Social = {
  id: number;
  platform: string;
  channel_id: string;
  active: boolean;
};
export type Member = {
  id: number;
  telegram_id: number;
  name: string;
  role: string;
};
export type TaskKind = 'post' | 'market' | 'recommendations' | 'statistics';
export type TaskSchedule = 'legacy' | 'interval' | 'daily' | 'weekly' | 'once';
export type TaskCatalogItem = { id: TaskKind; name: string; description: string; requires: string[] };
export type TaskInput = {
  kind: TaskKind; prompt: string; schedule_kind: TaskSchedule;
  interval_minutes: number; timezone: string; local_time: string; weekdays: number[];
  first_run_local?: string; channel_id?: number;
};
export type TaskRun = {
  id: number; scheduled_for: string; status: string; started_at: string | null;
  finished_at: string | null; result: string; error: string; post_id: number | null;
  sources: {title: string; url: string}[]; metrics: Record<string, unknown>;
};
export type TelegramAnalytics = {
  configured: boolean; web_search_configured: boolean; connected: boolean; can_connect: boolean;
  channels: {id: number; channel_id: string}[];
};
export type TaskItem = {
  id: number;
  prompt: string;
  interval_minutes: number;
  active: boolean;
  last_run: string | null;
  last_result?: { status: string; result: string; error: string } | null;
  kind: TaskKind; schedule_kind: TaskSchedule; timezone: string; local_time: string;
  weekdays: string; next_run: string | null; channel_id: number | null;
};
export type AuditItem = {
  id: number;
  company_id: number | null;
  action: string;
  details: string;
  created_at: string;
};
