// Cloudflare Worker: lets the dashboard's refresh button start a data update (GitHub Actions run).
// Secret GH_TOKEN: fine-grained GitHub token for jbirnie209/strategy-dashboard with "Actions: Read and write" only.
// Starts at most one run every 5 minutes, so the public endpoint can't be used to spam the repo.
const REPO = "jbirnie209/strategy-dashboard";
const ORIGIN = "https://jbirnie209.github.io";
const cors = { "Access-Control-Allow-Origin": ORIGIN, "Access-Control-Allow-Methods": "POST, OPTIONS", "Content-Type": "application/json" };
const reply = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: cors });

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    if (req.method !== "POST") return reply({ error: "POST only" }, 405);
    const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "strategy-dashboard-refresh" }
    });
    const last = (await (await gh("/actions/runs?per_page=1")).json()).workflow_runs?.[0];
    if (last && (last.status !== "completed" || Date.now() - Date.parse(last.created_at) < 5 * 60e3))
      return reply({ started: false, reason: "an update is running or ran in the last 5 minutes" });
    const r = await gh("/actions/workflows/update.yml/dispatches", { method: "POST", body: JSON.stringify({ ref: "main" }) });
    return reply({ started: r.status === 204 }, r.status === 204 ? 200 : 502);
  }
};
