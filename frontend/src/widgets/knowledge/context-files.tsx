import { ConfirmAction, Card, Input, Label } from "@/shared/ui";
import { useState } from 'react';
import { api } from '@/entities/marketing';
import { useLoad } from '@/shared/lib';

export function ContextFiles({ id }: { id: number }) {
  const [data, reload, loadErr] = useLoad(() => api.contextFiles(id), [id]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setErr('');
    try {
      await api.uploadContextFile(id, file);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
    setBusy(false);
  };
  if (data && !data.enabled)
    return (
      <Card className="card muted">
        Хранилище файлов (Yandex Object Storage) не настроено на сервере.
      </Card>
    );
  return (
    <Card className="card">
      <div className="cardHead">
        <b>Файлы контекста</b>
        <Label className="uploadBtn">
          {busy ? 'Загрузка…' : '+ Загрузить'}
          <Input
            type="file"
            disabled={busy}
            hidden
            accept=".txt,.md,.csv,.json,.html,.pdf,.docx"
            onChange={(e) => {
              upload(e.target.files?.[0]);
              e.target.value = '';
            }}
          />
        </Label>
      </div>
      <p className="muted">
        TXT, MD, CSV, JSON, PDF, DOCX до 10 МБ. Текст файлов агент использует
        как знания о компании.
      </p>
      {(err || loadErr) && <div className="error">{err || loadErr}</div>}
      {(data?.files ?? []).map((f) => (
        <div className="cardHead" key={f.name}>
          <span>
            {f.name}{' '}
            <span className="muted">
              · {Math.ceil(f.size / 1024)} КБ
              {f.supported ? '' : ' · формат не читается'}
            </span>
          </span>
          <ConfirmAction
            description={`Удалить файл «${f.name}»?`}
            onConfirm={async () => {
              await api.deleteContextFile(id, f.name);
              reload();
            }}
          >
            Удалить
          </ConfirmAction>
        </div>
      ))}
      {data?.files.length === 0 && <p className="muted">Файлов пока нет.</p>}
    </Card>
  );
}
