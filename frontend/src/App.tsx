import { useEffect, useState } from "react";
import { api, type Me } from "./api";
import { Admin } from "./views/Admin";

/** Mini App — только кабинет оператора. Сотрудники и администраторы компаний работают в чате с ботом. */
export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { api.me().then(setMe).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="app"><div className="card error">{error}</div></div>;
  if (!me) return <div className="app"><div className="card">Загрузка…</div></div>;

  if (me.role === "admin") return <Admin />;

  return (
    <div className="app narrow">
      <header className="top"><div className="brand"><span className="logo">AI</span> маркетолог</div></header>
      <div className="card">
        <h3>Работа — в чате с ботом</h3>
        <p>Ставьте задачи и согласовывайте материалы прямо в переписке с ботом. Этот кабинет нужен только оператору сервиса.</p>
      </div>
    </div>
  );
}
