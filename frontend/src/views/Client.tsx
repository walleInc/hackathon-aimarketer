import { useEffect, useState } from "react";
import { api, type Post } from "../api";
import { StatusChip } from "./ui";

export function Approvals() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [comment, setComment] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const load = () => api.posts().then(setPosts).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const act = async (id: number, d: "approve" | "reject" | "revise") => {
    try { await api.decide(id, d, comment[id] ?? ""); setError(""); await load(); }
    catch (e) { setError((e as Error).message); }
  };

  return (
    <div>
      {error && <div className="card error">{error}</div>}
      {posts.length === 0 && <div className="card muted">Постов пока нет.</div>}
      {posts.map((p) => (
        <div className="card" key={p.id}>
          <div className="meta">#{p.id} · v{p.version} · {p.platform} <StatusChip status={p.status} /></div>
          {p.image_url && <img src={p.image_url} alt="" />}
          <p className="postText">{p.text}</p>
          {p.check_notes && <div className="note">🔎 {p.check_notes}</div>}
          {p.error && <div className="error">{p.error}</div>}
          {p.status === "pending_approval" && (
            <>
              <input placeholder="Комментарий для доработки" value={comment[p.id] ?? ""}
                onChange={(e) => setComment({ ...comment, [p.id]: e.target.value })} />
              <div className="row">
                <button className="primary" onClick={() => act(p.id, "approve")}>Одобрить</button>
                <button onClick={() => act(p.id, "reject")}>Отклонить</button>
                <button disabled={!comment[p.id]} onClick={() => act(p.id, "revise")}>Доработать</button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export function Chat() {
  const [log, setLog] = useState<{ me: boolean; text: string }[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!text.trim() || busy) return;
    const t = text; setText(""); setBusy(true);
    setLog((l) => [...l, { me: true, text: t }]);
    try { const r = await api.chat(t); setLog((l) => [...l, { me: false, text: r.reply }]); }
    catch (e) { setLog((l) => [...l, { me: false, text: `Ошибка: ${(e as Error).message}` }]); }
    setBusy(false);
  };

  return (
    <div>
      {log.map((m, i) => <div key={i} className={`bubble ${m.me ? "me" : ""}`}>{m.text}</div>)}
      <div className="row">
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Например: подготовь пост про новую услугу" />
        <button className="primary" disabled={busy} onClick={send}>{busy ? "…" : "Отправить"}</button>
      </div>
    </div>
  );
}
