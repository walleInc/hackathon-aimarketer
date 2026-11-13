import { useCallback, useEffect, useState } from "react";
import { api, type Company, type Stat } from "../api";
import { ACTION_RU, Kpi, StatusChip, fmtDate } from "./ui";

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): [T | null, () => void, string] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(() => { fn().then(setData).catch((e) => setError(e.message)); }, deps);
  useEffect(load, [load]);
  return [data, load, error];
}

/** Технический администратор (companyId не задан) видит все компании; администратор компании — только свою. */
export function Admin({ companyId, ownerView }: { companyId?: number; ownerView: boolean }) {
  const [openId, setOpenId] = useState<number | null>(companyId ?? null);
  return (
    <div className="app wide">
      <header className="top">
        <div className="brand" onClick={() => !companyId && setOpenId(null)} style={{ cursor: companyId ? "default" : "pointer" }}>
          <span className="logo">AI</span> маркетолог <span className="badge">{companyId ? "кабинет компании" : "админ"}</span>
        </div>
      </header>
      {openId === null
        ? <Dashboard open={setOpenId} />
        : <CompanyPage id={openId} limitsEditable={ownerView} back={companyId ? undefined : () => setOpenId(null)} />}
    </div>
  );
}

/* ---------------- Дашборд ---------------- */

function Dashboard({ open }: { open: (id: number) => void }) {
  const [stats, reload, error] = useLoad(() => api.stats(), []);
  const [audit] = useLoad(() => api.audit(), []);
  const [creating, setCreating] = useState(false);

  const sum = (key: string) => (stats ?? []).reduce((a, s) => a + (s.posts[key] ?? 0), 0);
  const tokens = (stats ?? []).reduce((a, s) => a + s.tokens, 0);
  const cost = (stats ?? []).reduce((a, s) => a + s.cost_usd, 0);

  return (
    <>
      {error && <div className="card error">{error}</div>}
      <div className="kpis">
        <Kpi label="Компаний" value={stats?.length ?? "—"} />
        <Kpi label="Опубликовано" value={sum("published")} />
        <Kpi label="Ждут согласования" value={sum("pending_approval")} hint={sum("failed") ? `${sum("failed")} с ошибкой` : undefined} />
        <Kpi label="Токенов LLM" value={tokens.toLocaleString("ru-RU")}
          hint={cost > 0 ? `≈ $${cost.toFixed(4)} по тарифу модели` : "стоимость не задана (LLM_PRICE_*)"} />
      </div>

      <div className="sectionHead">
        <h2>Компании</h2>
        <button className="primary" onClick={() => setCreating(!creating)}>{creating ? "Отмена" : "+ Новая компания"}</button>
      </div>
      {creating && <NewCompany done={(id) => { setCreating(false); reload(); open(id); }} />}

      <div className="grid">
        {(stats ?? []).map((s) => <CompanyCard key={s.id} s={s} open={() => open(s.id)} />)}
        {stats?.length === 0 && <div className="card muted">Пока нет компаний. Создайте первую.</div>}
      </div>

      <div className="sectionHead"><h2>Последние действия</h2></div>
      <div className="card">
        {(audit ?? []).slice(0, 8).map((a) => (
          <div className="logRow" key={a.id}>
            <span className="muted">{fmtDate(a.created_at)}</span>
            <span>{ACTION_RU[a.action] ?? a.action}</span>
            <span className="muted">{a.details}</span>
          </div>
        ))}
        {audit?.length === 0 && <span className="muted">Журнал пуст.</span>}
      </div>
    </>
  );
}

function CompanyCard({ s, open }: { s: Stat; open: () => void }) {
  const ready = s.channels > 0 && s.users > 0;
  return (
    <div className="card clickable" onClick={open}>
      <div className="cardHead">
        <b>{s.name}</b>
        <span className={`dot ${ready ? "ok" : "warn"}`} title={ready ? "Готова к работе" : "Нужна настройка"} />
      </div>
      <div className="stats">
        <span><b>{s.posts.published ?? 0}</b> опубл.</span>
        <span><b>{s.posts.pending_approval ?? 0}</b> ждут</span>
        <span><b>{s.users}</b> в команде</span>
        <span><b>{s.channels}</b> каналов</span>
      </div>
      <div className="budget" title="Токены за текущий месяц / месячный бюджет">
        <div className="budgetBar"><span style={{ width: `${Math.min(100, (s.month_tokens / s.monthly_token_limit) * 100)}%` }}
          className={s.month_tokens >= s.monthly_token_limit ? "over" : ""} /></div>
        <small>{s.month_tokens.toLocaleString("ru-RU")} из {s.monthly_token_limit.toLocaleString("ru-RU")} токенов в месяц{s.cost_usd > 0 ? ` · $${s.cost_usd.toFixed(4)}` : ""}</small>
      </div>
      {!ready && <div className="hint">{s.channels === 0 ? "Не подключён канал" : "Нет сотрудников"}</div>}
    </div>
  );
}

function NewCompany({ done }: { done: (id: number) => void }) {
  const [f, setF] = useState({ name: "", description: "", brand_style: "" });
  const [err, setErr] = useState("");
  const submit = async () => {
    try { done((await api.createCompany(f)).id); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="card">
      <h3>Новая компания</h3>
      <label>Название<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>Чем занимается<textarea rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      <label>Стиль и требования бренда<textarea rows={2} value={f.brand_style} onChange={(e) => setF({ ...f, brand_style: e.target.value })} /></label>
      {err && <div className="error">{err}</div>}
      <button className="primary" disabled={!f.name.trim()} onClick={submit}>Создать</button>
    </div>
  );
}

/* ---------------- Карточка компании ---------------- */

const TABS = ["Обзор", "Знания", "Бренд", "Каналы", "Команда", "Задачи", "Посты", "Журнал"] as const;
type TabName = (typeof TABS)[number];

function CompanyPage({ id, back, limitsEditable }: { id: number; back?: () => void; limitsEditable: boolean }) {
  const [tab, setTab] = useState<TabName>("Обзор");
  const [companies] = useLoad(() => api.companies(), [id]);
  const company = companies?.find((c) => c.id === id);

  return (
    <>
      {back && <div className="crumbs"><a onClick={back}>← Все компании</a></div>}
      <h1>{company?.name ?? "…"}</h1>
      <nav className="tabs scroll">
        {TABS.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </nav>
      {company && tab === "Обзор" && <Overview company={company} go={setTab} limitsEditable={limitsEditable} />}
      {tab === "Знания" && <Knowledge id={id} />}
      {company && tab === "Бренд" && <BrandKit company={company} />}
      {tab === "Каналы" && <Channels id={id} />}
      {tab === "Команда" && <Team id={id} />}
      {tab === "Задачи" && <Tasks id={id} />}
      {tab === "Посты" && <Posts id={id} />}
      {tab === "Журнал" && <Log id={id} />}
    </>
  );
}

function Overview({ company, go, limitsEditable }: { company: Company; go: (t: TabName) => void; limitsEditable: boolean }) {
  const [f, setF] = useState({
    name: company.name, description: company.description, brand_style: company.brand_style,
    daily_post_limit: company.daily_post_limit, monthly_token_limit: company.monthly_token_limit,
  });
  const [msg, setMsg] = useState("");
  const [docs] = useLoad(() => api.knowledge(company.id), [company.id]);
  const [socials] = useLoad(() => api.socials(company.id), [company.id]);
  const [members] = useLoad(() => api.members(company.id), [company.id]);
  const steps: [string, boolean, TabName][] = [
    ["Загружены знания о компании", (docs?.length ?? 0) > 0, "Знания"],
    ["Подключён канал для публикаций", (socials ?? []).some((s) => s.active), "Каналы"],
    ["Есть администратор компании (согласующий)", (members ?? []).some((m) => m.role === "approver"), "Команда"],
  ];
  const save = async () => {
    try {
      const { daily_post_limit, monthly_token_limit, ...profile } = f;
      await api.updateCompany(company.id, limitsEditable ? f : profile);
      setMsg("Сохранено");
    } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <div className="split">
      <div className="card">
        <h3>Профиль и бренд</h3>
        <label>Название<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Чем занимается<textarea rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <label>Тон и стиль общения<textarea rows={3} value={f.brand_style} onChange={(e) => setF({ ...f, brand_style: e.target.value })} /></label>
        <h3 style={{ marginTop: 16 }}>Лимиты</h3>
        <div className="row2">
          <label>Материалов в сутки<input type="number" min={1} disabled={!limitsEditable} value={f.daily_post_limit} onChange={(e) => setF({ ...f, daily_post_limit: Number(e.target.value) })} /></label>
          <label>Токенов AI в месяц<input type="number" min={1000} step={10000} disabled={!limitsEditable} value={f.monthly_token_limit} onChange={(e) => setF({ ...f, monthly_token_limit: Number(e.target.value) })} /></label>
        </div>
        <p className="muted">При превышении агент останавливается и уведомляет администратора — расходы не выходят за рамки.</p>
        <div className="row"><button className="primary" onClick={save}>Сохранить</button><span className="muted">{msg}</span></div>
      </div>
      <div className="card">
        <h3>Готовность к работе</h3>
        {steps.map(([label, ok, tab]) => (
          <div key={label} className="check" onClick={() => go(tab)}>
            <span className={`dot ${ok ? "ok" : "warn"}`} /> <span>{label}</span>
            <span className="muted">{ok ? "готово" : "настроить →"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Knowledge({ id }: { id: number }) {
  const [docs, reload] = useLoad(() => api.knowledge(id), [id]);
  // editing = null (создание нового) или id редактируемого документа
  const [editing, setEditing] = useState<number | null>(null);
  const [d, setD] = useState({ title: "", content: "" });
  const [err, setErr] = useState("");

  const startEdit = (x: { id: number; title: string; content: string }) => { setEditing(x.id); setD({ title: x.title, content: x.content }); setErr(""); };
  const reset = () => { setEditing(null); setD({ title: "", content: "" }); setErr(""); };
  const save = async () => {
    try {
      if (editing === null) await api.addKnowledge(id, d.title, d.content);
      else await api.updateKnowledge(editing, d.title, d.content);
      reset(); reload();
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="split">
      <div className="card">
        <h3>{editing === null ? "Добавить знания" : "Редактирование документа"}</h3>
        <label>Название<input placeholder="О компании, Продукты, Конкуренты…" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} /></label>
        <label>Текст<textarea rows={10} value={d.content} onChange={(e) => setD({ ...d, content: e.target.value })} /></label>
        {err && <div className="error">{err}</div>}
        <div className="row">
          <button className="primary" disabled={!d.title || !d.content} onClick={save}>{editing === null ? "Добавить" : "Сохранить изменения"}</button>
          {editing !== null && <button onClick={reset}>Отмена</button>}
        </div>
        {editing !== null && <p className="muted">Агент начнёт использовать обновлённый текст со следующего запроса.</p>}
      </div>
      <div>
        {(docs ?? []).map((x) => (
          <div className={`card ${editing === x.id ? "active" : ""}`} key={x.id}>
            <div className="cardHead"><b>{x.title}</b>
              <span>
                <button className="ghost" onClick={() => startEdit(x)}>Изменить</button>
                <button className="ghost" onClick={async () => { if (confirm(`Удалить «${x.title}»?`)) { await api.deleteKnowledge(x.id); if (editing === x.id) reset(); reload(); } }}>Удалить</button>
              </span></div>
            <p className="clip">{x.content}</p>
            <span className="muted">{x.size} симв.{x.updated_at ? ` · изменён ${fmtDate(x.updated_at)}` : ""}</span>
          </div>
        ))}
        {docs?.length === 0 && <div className="card muted">База знаний пуста. Агент не сможет опираться на факты о компании.</div>}
      </div>
    </div>
  );
}

const KINDS: [string, string, string][] = [
  ["logo_color", "Логотип — основной цвет", "для светлых фонов, PNG"],
  ["logo_white", "Логотип — белый", "для тёмных фонов, PNG"],
  ["logo_black", "Логотип — чёрный", "монохромная печать, PNG"],
  ["icon", "Графический знак", "без текстовой части, PNG"],
  ["pattern", "Паттерны", "фирменные узоры, PNG/JPG"],
  ["font_heading", "Шрифт заголовков", "TTF/OTF"],
  ["font_body", "Шрифт основного текста", "TTF/OTF"],
  ["example", "Примеры оформления", "образцы, PNG/JPG"],
];

function BrandKit({ company }: { company: Company }) {
  const id = company.id;
  const [assets, reload] = useLoad(() => api.assets(id), [id]);
  const [f, setF] = useState({ brand_colors: company.brand_colors, brand_rules: company.brand_rules });
  const [msg, setMsg] = useState("");
  const [prev, setPrev] = useState<{ url: string; style: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const colors = f.brand_colors.match(/#[0-9a-fA-F]{6}/g) ?? [];

  const save = async () => { try { await api.updateCompany(id, f); setMsg("Сохранено"); } catch (e) { setMsg((e as Error).message); } };
  const upload = async (kind: string, file: File | undefined) => {
    if (!file) return;
    try { await api.uploadAsset(id, kind, file); setMsg(""); reload(); } catch (e) { setMsg((e as Error).message); }
  };
  const preview = async (style: "dark" | "light") => {
    setBusy(true);
    try { setPrev({ url: (await api.preview(id, company.name, "Пробная карточка в фирменном стиле", style)).url, style }); }
    catch (e) { setMsg((e as Error).message); }
    setBusy(false);
  };

  return (
    <div className="split">
      <div>
        <div className="card">
          <h3>Фирменные цвета</h3>
          <label>HEX через запятую, основной первым<input value={f.brand_colors} onChange={(e) => setF({ ...f, brand_colors: e.target.value })} placeholder="#196C7F, #285055, #DDE1E1" /></label>
          <div className="swatches">{colors.map((c) => <span key={c} className="swatch" style={{ background: c }} title={c} />)}</div>
        </div>
        <div className="card">
          <h3>Правила бренда</h3>
          <label>Что можно и нельзя (агент соблюдает и проверяет каждый материал)
            <textarea rows={10} value={f.brand_rules} onChange={(e) => setF({ ...f, brand_rules: e.target.value })} /></label>
          <div className="row"><button className="primary" onClick={save}>Сохранить</button><span className="muted">{msg}</span></div>
        </div>
        <div className="card">
          <h3>Предпросмотр карточки</h3>
          <p className="muted">Так будет выглядеть изображение к посту: шрифты, цвета и логотип из бренд-кита.</p>
          <div className="row">
            <button disabled={busy} onClick={() => preview("dark")}>Тёмная</button>
            <button disabled={busy} onClick={() => preview("light")}>Светлая</button>
          </div>
          {prev && <img className="previewImg" src={prev.url} alt="Предпросмотр" />}
        </div>
      </div>
      <div>
        {KINDS.map(([kind, title, hint]) => {
          const items = (assets ?? []).filter((a) => a.kind === kind);
          return (
            <div className="card" key={kind}>
              <div className="cardHead"><b>{title}</b>
                <label className="uploadBtn">+ Загрузить
                  <input type="file" hidden onChange={(e) => { upload(kind, e.target.files?.[0]); e.target.value = ""; }} /></label>
              </div>
              <span className="muted">{hint}</span>
              <div className="thumbs">
                {items.map((a) => (
                  <div className="thumb" key={a.id}>
                    {kind.startsWith("font") ? <span className="fontName">Aa</span> : <img src={a.url} alt={a.filename} />}
                    <small>{a.filename}</small>
                    <button className="ghost" onClick={async () => { await api.deleteAsset(a.id); reload(); }}>×</button>
                  </div>
                ))}
                {items.length === 0 && <span className="muted">не загружено</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Channels({ id }: { id: number }) {
  const [list, reload] = useLoad(() => api.socials(id), [id]);
  const [ch, setCh] = useState("");
  const [err, setErr] = useState("");
  return (
    <div className="split">
      <div className="card">
        <h3>Подключить канал Telegram</h3>
        <label>@username или ID канала<input placeholder="@channel или -100…" value={ch} onChange={(e) => setCh(e.target.value)} /></label>
        <p className="muted">Бот должен быть администратором канала с правом публикации.</p>
        {err && <div className="error">{err}</div>}
        <button className="primary" disabled={!ch}
          onClick={async () => { try { await api.addSocial(id, ch); setCh(""); setErr(""); reload(); } catch (e) { setErr((e as Error).message); } }}>Подключить</button>
      </div>
      <div>
        {(list ?? []).map((s) => (
          <div className="card" key={s.id}>
            <div className="cardHead"><b>{s.channel_id}</b><span className={`dot ${s.active ? "ok" : "off"}`} /></div>
            <span className="muted">{s.platform} · {s.active ? "активен" : "доступ отозван"}</span>
            {s.active && <div className="row"><button className="ghost" onClick={async () => { await api.revokeSocial(s.id); reload(); }}>Отозвать доступ</button></div>}
          </div>
        ))}
        {list?.length === 0 && <div className="card muted">Каналов нет.</div>}
        <div className="card muted">VK и MAX — в разработке.</div>
      </div>
    </div>
  );
}

function Team({ id }: { id: number }) {
  const [members, reload] = useLoad(() => api.members(id), [id]);
  const [code, setCode] = useState("");
  const invite = async (role: string) => { setCode((await api.invite(id, role)).code); reload(); };
  const ROLE: Record<string, string> = { approver: "Администратор компании", member: "Сотрудник", admin: "Тех. аккаунт" };
  return (
    <div className="split">
      <div className="card">
        <h3>Пригласить в компанию</h3>
        <div className="row">
          <button className="primary" onClick={() => invite("approver")}>Администратор компании</button>
          <button onClick={() => invite("member")}>Сотрудник</button>
        </div>
        {code && <p>Отправьте ссылку (одноразовая):<br /><code>https://t.me/aimarketologgbot?start={code}</code></p>}
        <p className="muted">
          Администратор компании согласует публикации в чате бота и сам приглашает сотрудников командой /invite.
          Сотрудник ставит задачи в чате. 
        </p>
      </div>
      <div>
        {(members ?? []).map((m) => (
          <div className="card" key={m.id}>
            <div className="cardHead"><b>{m.name || `ID ${m.telegram_id}`}</b><span className="badge">{ROLE[m.role] ?? m.role}</span></div>
            <span className="muted">Telegram ID {m.telegram_id}</span>
          </div>
        ))}
        {members?.length === 0 && <div className="card muted">В команде пока никого.</div>}
      </div>
    </div>
  );
}

function Tasks({ id }: { id: number }) {
  const [tasks, reload] = useLoad(() => api.tasks(id), [id]);
  const [t, setT] = useState({ prompt: "", hours: 24 });
  const every = (min: number) => (min % 1440 === 0 ? `каждые ${min / 1440} дн.` : min % 60 === 0 ? `каждые ${min / 60} ч.` : `каждые ${min} мин.`);
  return (
    <div className="split">
      <div className="card">
        <h3>Регулярная задача</h3>
        <label>Что делать<textarea rows={3} placeholder="Подготовь пост про одну из позиций меню" value={t.prompt} onChange={(e) => setT({ ...t, prompt: e.target.value })} /></label>
        <label>Периодичность, часов<input type="number" min={1} value={t.hours} onChange={(e) => setT({ ...t, hours: Number(e.target.value) })} /></label>
        <button className="primary" disabled={!t.prompt || t.hours < 1}
          onClick={async () => { await api.createTask(id, t.prompt, t.hours * 60); setT({ prompt: "", hours: 24 }); reload(); }}>Создать</button>
        <p className="muted">Агент сам готовит материал и отправляет на согласование.</p>
      </div>
      <div>
        {(tasks ?? []).map((x) => (
          <div className="card" key={x.id}>
            <div className="cardHead"><b>{every(x.interval_minutes)}</b>
              <button className="ghost" onClick={async () => { await api.toggleTask(x.id, !x.active); reload(); }}>{x.active ? "Выключить" : "Включить"}</button></div>
            <p>{x.prompt}</p>
            <span className="muted">Последний запуск: {fmtDate(x.last_run)} · {x.active ? "активна" : "выключена"}</span>
          </div>
        ))}
        {tasks?.length === 0 && <div className="card muted">Регулярных задач нет.</div>}
      </div>
    </div>
  );
}

function Posts({ id }: { id: number }) {
  const [posts] = useLoad(() => api.companyPosts(id), [id]);
  return (
    <div>
      {(posts ?? []).map((p) => (
        <div className="card" key={p.id}>
          <div className="meta">#{p.id} · v{p.version} · {p.platform} · {fmtDate(p.created_at)} <StatusChip status={p.status} /></div>
          {p.image_url && <img className="postImg" src={p.image_url} alt="" />}
          <p className="postText">{p.text}</p>
          {p.check_notes && <div className="note">🔎 {p.check_notes}</div>}
          {p.error && <div className="error">{p.error}</div>}
        </div>
      ))}
      {posts?.length === 0 && <div className="card muted">Постов пока нет.</div>}
    </div>
  );
}

function Log({ id }: { id: number }) {
  const [rows] = useLoad(() => api.audit(id), [id]);
  return (
    <div className="card">
      {(rows ?? []).map((a) => (
        <div className="logRow" key={a.id}>
          <span className="muted">{fmtDate(a.created_at)}</span>
          <span>{ACTION_RU[a.action] ?? a.action}</span>
          <span className="muted">{a.details}</span>
        </div>
      ))}
      {rows?.length === 0 && <span className="muted">Журнал пуст.</span>}
    </div>
  );
}
