// Песенник: статика из songbook/ + маленький API для хозяина.
//   GET  /api/state          — всем: скрытые табы, отметки, список «хочу найти»
//   GET  /api/check          — проверить ключ хозяина
//   POST /api/hide  {slug, hidden}         — убрать таб / вернуть
//   POST /api/mark  {slug, d?, f?}         — сложность d 0..4, знакомство f 0..4
//   POST /api/wish  {add:{text,url}} | {del:id}
// Писать можно только с заголовком x-key = секрет OWNER_KEY (wrangler secret put OWNER_KEY).
const SLUG = /^[a-z0-9][a-z0-9-]{0,150}$/;
const now = () => new Date().toISOString().slice(0, 19).replace("T", " ");
const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

async function state(db) {
  const [h, m, w] = await db.batch([
    db.prepare("SELECT slug FROM hidden ORDER BY at DESC"),
    db.prepare("SELECT slug, d, f FROM marks"),
    db.prepare("SELECT id, text, url, at FROM wish ORDER BY id"),
  ]);
  const marks = {};
  for (const r of m.results) marks[r.slug] = { d: r.d, f: r.f };
  return { hidden: h.results.map((r) => r.slug), marks, wish: w.results };
}

async function api(req, env, path) {
  const db = env.DB;
  if (req.method === "GET" && path === "/api/state") return json(await state(db));
  const owner = !!env.OWNER_KEY && req.headers.get("x-key") === env.OWNER_KEY;
  if (path === "/api/check") return json({ owner }, owner ? 200 : 403);
  if (req.method !== "POST") return json({ error: "method" }, 405);
  if (!owner) return json({ error: "нужен ключ хозяина" }, 403);
  let body;
  try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }

  if (path === "/api/hide") {
    if (!SLUG.test(body.slug || "")) return json({ error: "slug" }, 400);
    await (body.hidden
      ? db.prepare("INSERT OR REPLACE INTO hidden (slug, at) VALUES (?, ?)").bind(body.slug, now())
      : db.prepare("DELETE FROM hidden WHERE slug = ?").bind(body.slug)).run();
  } else if (path === "/api/mark") {
    if (!SLUG.test(body.slug || "")) return json({ error: "slug" }, 400);
    const lvl = (v) => (Number.isInteger(v) && v >= 0 && v <= 4 ? v : null);
    const d = lvl(body.d), f = lvl(body.f);
    if (d === null && f === null) return json({ error: "d/f" }, 400);
    await db.prepare(
      "INSERT INTO marks (slug, d, f, at) VALUES (?1, COALESCE(?2, 0), COALESCE(?3, 0), ?4) " +
      "ON CONFLICT(slug) DO UPDATE SET d = COALESCE(?2, d), f = COALESCE(?3, f), at = ?4"
    ).bind(body.slug, d, f, now()).run();
  } else if (path === "/api/wish") {
    if (body.add) {
      const text = String(body.add.text || "").trim().slice(0, 300);
      let url = String(body.add.url || "").trim().slice(0, 600);
      if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
      if (!text && !url) return json({ error: "пусто" }, 400);
      await db.prepare("INSERT INTO wish (text, url, at) VALUES (?, ?, ?)").bind(text, url, now()).run();
    } else if (Number.isInteger(body.del)) {
      await db.prepare("DELETE FROM wish WHERE id = ?").bind(body.del).run();
    } else return json({ error: "add/del" }, 400);
  } else return json({ error: "not found" }, 404);
  return json(await state(db));
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname.startsWith("/api/")) {
      try { return await api(req, env, url.pathname); }
      catch (e) { return json({ error: String(e && e.message || e) }, 500); }
    }
    return env.ASSETS.fetch(req);
  },
};
