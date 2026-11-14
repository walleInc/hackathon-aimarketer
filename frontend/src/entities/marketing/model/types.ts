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

export type MetricName = 'views' | 'reactions' | 'forwards' | 'comments';
export type Measurement = { value: number | null; observed_at: string | null; source: string };
export type AnalyticsPost = {
  id: number; text: string; platform: string; channel_id: string; external_id: string;
  published_at: string | null; has_image: boolean;
  metrics: Record<MetricName, Measurement>; reaction_rate: number | null;
};
export type AnalyticsAdvice = { text: string; created_at: string; stale: boolean };
export type PostAnalytics = {
  period_days: number; published_posts: number; sample_size: number; max_posts: number;
  unknown_publication_dates: number;
  summary: Record<MetricName, { total: number | null; measured_posts: number }> & {
    reaction_rate: number | null; rate_posts: number;
  };
  posts: AnalyticsPost[];
  daily_publications: { date: string; posts: number }[];
  recommendations: { title: string; text: string; post_ids: number[] }[];
  ai_advice: AnalyticsAdvice | null;
};
export type AgentRun = {
  id: number;
  kind: string;
  prompt: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  result: string;
  image_url: string;
  error: string;
  post_id: number | null;
  parent_run_id: number | null;
  created_at: string;
};

export type ChatMessage = {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  run_id: number | null;
  post_id: number | null;
  image_url: string;
};

export type ChatPage = { items: ChatMessage[]; next_cursor: number | null };
