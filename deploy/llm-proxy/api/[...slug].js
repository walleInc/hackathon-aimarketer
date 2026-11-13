// Тот же прокси для Vercel (Edge Function). Адрес: https://<проект>.vercel.app/api/<PROXY_TOKEN>/<провайдер>/<путь API>
// Переменная окружения: PROXY_TOKEN. Подробности — в main.ts.
export const config = { runtime: "edge" };

const UPSTREAMS = {
  openai: "https://api.openai.com",
  groq: "https://api.groq.com",
  openrouter: "https://openrouter.ai",
  anthropic: "https://api.anthropic.com",
};

const DROP = ["host", "forwarded", "via", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip",
  "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor", "x-vercel-forwarded-for", "x-vercel-ip-country",
  "x-vercel-id", "x-vercel-ip-city", "x-vercel-ip-country-region", "x-vercel-deployment-url", "x-vercel-proxied-for"];

async function safeEqual(a, b) {
  const enc = new TextEncoder();
  const [x, y] = (await Promise.all([a, b].map((s) => crypto.subtle.digest("SHA-256", enc.encode(s))))).map((d) => new Uint8Array(d));
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export default async function handler(req) {
  const url = new URL(req.url);
  const segs = url.pathname.split("/").filter(Boolean);
  if (segs[0] === "api") segs.shift();
  const [token, upstream, ...rest] = segs;
  const secret = process.env.PROXY_TOKEN ?? "";

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
