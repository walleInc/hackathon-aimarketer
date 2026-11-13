import { useEffect, useState } from "react";
import { api, type Me } from "./api";
import { Admin } from "./views/Admin";
import { Approvals, Chat } from "./views/Client";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"approve" | "chat">("approve");

  useEffect(() => { api.me().then(setMe).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="app"><div className="card error">{error}</div></div>;
  if (!me) return <div className="app"><div className="card">Загрузка…</div></div>;

  if (me.role === "admin") return <Admin />;

  return (
    <div className="app narrow">
      <header className="top">
        <div className="brand"><span className="logo">AI</span> маркетолог</div>
        <span className="muted">{me.company?.name}</span>
      </header>
      <nav className="tabs">
        <button className={tab === "approve" ? "on" : ""} onClick={() => setTab("approve")}>Согласование</button>
        <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>Чат</button>
      </nav>
      {tab === "approve" ? <Approvals /> : <Chat />}
    </div>
  );
}
