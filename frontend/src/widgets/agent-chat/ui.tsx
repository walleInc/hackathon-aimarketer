import { useEffect, useRef, useState } from 'react';
import { api, type AgentRun, type ChatMessage, type Post, StatusChip } from '@/entities/marketing';
import { Button, Card, Textarea, Input, Label, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/shared/ui';

const utcDate = (value: string) => new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('ru-RU', { timeZone: 'UTC' }) + ' UTC';
const merge = (old: ChatMessage[], incoming: ChatMessage[]) =>
  [...new Map([...old, ...incoming].map(m => [m.id, m])).values()].sort((a, b) => a.id - b.id);

export function AgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [text, setText] = useState('');
  const [reference, setReference] = useState<File | null>(null);
  const [parent, setParent] = useState<number | undefined>();
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [loading, setLoading] = useState(true);
  const [post, setPost] = useState<Post | null>(null);
  const [refresh, setRefresh] = useState(0);
  const olderLoaded = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      let active = false;
      try {
        const [page, executions] = await Promise.all([api.messages(), api.agentRuns()]);
        if (cancelled) return;
        setMessages(old => merge(old, page.items));
        if (!olderLoaded.current) setCursor(page.next_cursor);
        setRuns(executions);
        active = executions.some(r => r.status === 'queued' || r.status === 'running');
        setError('');
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
        active = true;
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(load, active ? 3000 : 15000);
        }
      }
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [refresh]);

  const loadOlder = async () => {
    if (!cursor) return;
    setLoadingOlder(true);
    try {
      const page = await api.messages(cursor);
      olderLoaded.current = true;
      setMessages(old => merge(old, page.items));
      setCursor(page.next_cursor);
    } catch (e) { setError((e as Error).message); }
    finally { setLoadingOlder(false); }
  };

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim() || sending) return;
    if (reference && reference.size > 10 * 1024 * 1024) {
      setError('Изображение должно быть не больше 10 МБ');
      return;
    }
    setSending(true);
    setError('');
    try {
      const run = reference ? await api.startReferenceRun(text.trim(), reference, parent) : await api.startRun(text.trim(), parent);
      setRuns(old => [...old.filter(r => r.id !== run.id), run]);
      setText('');
      setReference(null);
      setParent(undefined);
      if (fileInput.current) fileInput.current.value = '';
      setRefresh(value => value + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  };

  const openPost = async (id: number) => {
    try { setPost(await api.post(id)); }
    catch (e) { setError((e as Error).message); }
  };

  return <section className="agent-chat" aria-label="Чат с ИИ">
    <h2>ИИ-маркетолог</h2>
    <p className="muted">Задайте задачу или уточните результат. Переписка сохраняется, даты указаны в UTC.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {cursor && <Button variant="outline" onClick={loadOlder} disabled={loadingOlder}>Предыдущие сообщения</Button>}
    {loading && <p role="status">Загрузка истории…</p>}
    <div className="chat-messages" role="log" aria-label="История диалога" aria-live="polite">
      {!loading && messages.length === 0 && <Card className="card muted">Напишите первое сообщение.</Card>}
      {messages.map(message => <Card className={`card chat-message chat-${message.role}`} key={message.id}>
        <div className="cardHead"><b>{message.role === 'user' ? 'Вы' : 'ИИ'}</b><time dateTime={`${message.created_at}Z`}>{utcDate(message.created_at)}</time></div>
        <p className="chat-text">{message.content}</p>
        {message.image_url && <img className="chat-image" src={message.image_url} alt="Результат работы ИИ" />}
        <div className="chat-actions">
          {message.post_id && <Button variant="outline" onClick={() => openPost(message.post_id!)}>Открыть материал #{message.post_id}</Button>}
          {message.role === 'assistant' && message.run_id && <Button variant="ghost" onClick={() => { setParent(message.run_id!); input.current?.focus(); }}>Уточнить результат #{message.run_id}</Button>}
        </div>
      </Card>)}
    </div>
    <div aria-live="polite">
      {runs.filter(run => run.status === 'queued' || run.status === 'running').map(run =>
        <Card className="card" key={run.id} role="status">Задача #{run.id}: {run.status === 'queued' ? 'в очереди' : 'выполняется'}<p>{run.prompt}</p></Card>)}
    </div>
    <form className="card" onSubmit={send}>
      {parent && <p>Уточнение к задаче #{parent} <Button type="button" variant="ghost" onClick={() => setParent(undefined)}>Отменить привязку</Button></p>}
      <Label htmlFor="agent-message">Задача или вопрос</Label>
      <Textarea id="agent-message" ref={input} rows={3} maxLength={4000} value={text} onChange={event => setText(event.target.value)} placeholder="Что мы подготовили вчера?" />
      <Label htmlFor="agent-reference">Изображение-референс (необязательно, до 10 МБ)</Label>
      <Input id="agent-reference" ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" onChange={event => setReference(event.target.files?.[0] ?? null)} />
      <Button type="submit" disabled={sending || !text.trim()}>{sending ? 'Отправка…' : 'Отправить'}</Button>
    </form>
    <Dialog open={!!post} onOpenChange={open => { if (!open) setPost(null); }}>
      <DialogContent><DialogHeader><DialogTitle>Материал #{post?.id}</DialogTitle><DialogDescription>Текущее состояние материала</DialogDescription></DialogHeader>
        {post && <><StatusChip status={post.status} /><p className="chat-text">{post.text}</p>{post.image_url && <img className="chat-image" src={post.image_url} alt="Изображение материала" />}</>}
      </DialogContent>
    </Dialog>
  </section>;
}
