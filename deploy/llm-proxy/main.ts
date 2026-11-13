// Прокси к LLM-провайдерам для сервера в РФ (Deno Deploy). Бесплатно, ключей не хранит.
// Адрес для приложения:  https://<проект>.deno.dev/<PROXY_TOKEN>/<провайдер>/<путь API>
//   OpenAI      -> OPENAI_BASE_URL=https://<проект>.deno.dev/<PROXY_TOKEN>/openai/v1
//   Groq        -> OPENAI_BASE_URL=https://<проект>.deno.dev/<PROXY_TOKEN>/groq/openai/v1
//   OpenRouter  -> OPENAI_BASE_URL=https://<проект>.deno.dev/<PROXY_TOKEN>/openrouter/api/v1
// Токен в пути закрывает прокси от посторонних; ключ провайдера клиент передаёт в Authorization как обычно.

const UPSTREAMS: Record<string, string> = {
  openai: "https://api.openai.com",
  groq: "https://api.groq.com",
  openrouter: "https://openrouter.ai",
  anthropic: "https://api.anthropic.com",
};

const DROP = ["host", "forwarded", "via", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip",
  "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor", "x-vercel-forwarded-for", "x-vercel-ip-country"];

async function safeEqual(a: string, b: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [x, y] = (await Promise.all([a, b].map((s) => crypto.subtle.digest("SHA-256", enc.encode(s))))).map((d) => new Uint8Array(d));
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export async function handle(req: Request, secret: string): Promise<Response> {
  const url = new URL(req.url);
  const segs = url.pathname.split("/").filter(Boolean);
  if (segs[0] === "api") segs.shift(); // для Vercel: файл лежит в /api
  const [token, upstream, ...rest] = segs;

  if (!secret || !(await safeEqual(token ?? "", secret)) || !(upstream in UPSTREAMS)) {
    return new Response("Not found", { status: 404 });
  }

  const headers = new Headers(req.headers);
  for (const h of DROP) headers.delete(h);

  return fetch(`${UPSTREAMS[upstream]}/${rest.join("/")}${url.search}`, {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer(),
    redirect: "manual",
  });
}

if (typeof Deno !== "undefined") {
  Deno.serve((req) => handle(req, Deno.env.get("PROXY_TOKEN") ?? ""));
}
