// 秘塔提交 sidecar: 用 Node 全局 fetch(undici) 对齐 EOS 的 HTTP 栈。
// Python 后端只把请求体 POST 到本机 127.0.0.1:8791，不直接连秘塔。
// 仅监听 loopback；API key 只从启动环境读取，不出现在请求/日志里。
import http from 'node:http';
import crypto from 'node:crypto';

const PORT = Number(process.env.METASO_SIDECAR_PORT || 8791);
const BASE = (process.env.MINIMAX_BASE_URL || 'https://metaso.cn/api/minimax/v2')
  .replace(/\/$/, '');
const KEY = process.env.MINIMAX_API_KEY || '';
if (!KEY) {
  console.error('[metaso-sidecar] MINIMAX_API_KEY missing');
  process.exit(2);
}
const KEY_SHA = crypto.createHash('sha256').update(KEY).digest('hex').slice(0, 8);

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    send(res, 200, {
      ok: true, service: 'aimf-metaso-submit', base: BASE,
      key_sha: KEY_SHA, pid: process.pid, node: process.version,
    });
    return;
  }
  if (req.method !== 'POST' || req.url !== '/submit') {
    send(res, 404, { ok: false, error: 'not found' });
    return;
  }

  let raw = '';
  try {
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > 80 * 1024 * 1024) {
        send(res, 413, { ok: false, error: 'payload too large' });
        return;
      }
    }
    const payload = JSON.parse(raw || '{}');
    const body = payload.body;
    if (!body || typeof body !== 'object') {
      send(res, 400, { ok: false, error: 'body required' });
      return;
    }
    const headers = {
      Authorization: `Bearer ${KEY}`,
      'Content-Type': 'application/json',
    };
    if (payload.idempotency_key) {
      headers['Idempotency-Key'] = String(payload.idempotency_key);
    }
    try {
      // 与 EOS workbench/lib/providers/http.mjs 对齐:
      // 全局 fetch + 90s AbortSignal + redirect:error。
      const r = await fetch(`${BASE}/video_generation`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        redirect: 'error',
        signal: AbortSignal.timeout(90000),
      });
      const text = await r.text();
      send(res, 200, { ok: r.ok, status: r.status, text });
    } catch (e) {
      // 连接层断连: Python 侧会用 SubmitAmbiguous + 任务列表核对处理
      send(res, 200, { ok: false, network: true, error: String(e?.message || e) });
    }
  } catch (e) {
    send(res, 400, { ok: false, error: String(e?.message || e) });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[metaso-sidecar] http://127.0.0.1:${PORT} -> ${BASE} `
    + `node ${process.version} pid ${process.pid}`);
});

const shutdown = () => server.close(() => process.exit(0));
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
