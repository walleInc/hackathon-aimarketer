import { useEffect, useState } from "react";
import { api, type Me } from "./api";
import { Admin } from "./views/Admin";

/** Mini App — кабинет: тех. администратор видит все компании, администратор компании — свою. Сотрудники работают в чате. */
export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { api.me().then(setMe).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="app"><div className="card error">{error}</div></div>;
  if (!me) return <div className="app"><div className="card">Загрузка…</div></div>;

  if (me.role === "admin") return <Admin ownerView />;
  if (me.role === "approver" && me.company) return <Admin companyId={me.company.id} ownerView={false} />;

  return (
    <div className="app narrow">
      <header className="top"><div className="brand"><span className="logo">AI</span> маркетолог</div></header>
      <div className="card">
        <h3>Работа — в чате с ботом</h3>
        <p>Ставьте задачи и согласовывайте материалы прямо в переписке с ботом. Кабинет нужен администратору компании.</p>
      </div>
    </div>
  );
}
