import { api, ACTION_RU, fmtDate } from "@/entities/marketing";
import { useLoad } from '@/shared/lib';
import { Card } from '@/shared/ui';

export function Log({ id }: { id: number }) {
  const [rows, , loadError] = useLoad(() => api.audit(id), [id]);
  return (
    <Card className="card">
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {(rows ?? []).map((a) => (
        <div className="logRow" key={a.id}>
          <span className="muted">{fmtDate(a.created_at)}</span>
          <span>{ACTION_RU[a.action] ?? a.action}</span>
          <span className="muted">{a.details}</span>
        </div>
      ))}
      {rows?.length === 0 && <span className="muted">Журнал пуст.</span>}
    </Card>
  );
}
