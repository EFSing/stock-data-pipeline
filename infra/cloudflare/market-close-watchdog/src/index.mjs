/*
 * Cloudflare Cron fallback for GitHub Actions market-close workflows.
 *
 * This Worker never reads market data, holdings, broker state, or the VPS.  It
 * only asks GitHub whether the expected workflow has a recent active/success
 * run and dispatches the same repository-owned workflow when it is missing or
 * failed.  The workflow/CLI remains the single session-resolution authority.
 */

const API_VERSION = "2022-11-28";
const LOOKBACK_MS = 90 * 60 * 1000;
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

export const WORKFLOWS = Object.freeze({
  CN: Object.freeze({
    DAILY_REPORT: "cn-daily-report.yml",
    D1_PROSPECTIVE: "setup01-d1-vps-natural-collector-cn.yml",
  }),
  US: Object.freeze({
    DAILY_REPORT: "us-daily-report.yml",
    D1_PROSPECTIVE: "setup01-d1-vps-natural-collector-us.yml",
  }),
});

export const CRON_ROUTES = Object.freeze({
  "45 9 * * 1-5": Object.freeze({ market: "CN", kinds: ["DAILY_REPORT"] }),
  "55 10 * * 1-5": Object.freeze({ market: "CN", kinds: ["D1_PROSPECTIVE"] }),
  "15 1 * * 2-6": Object.freeze({ market: "US", kinds: ["DAILY_REPORT"] }),
  "55 1 * * 2-6": Object.freeze({ market: "US", kinds: ["D1_PROSPECTIVE"] }),
});

function repository(env) {
  const configured = String(env.GITHUB_REPOSITORY || "EFSing/stock-data-pipeline").trim();
  const parts = configured.split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw new Error("GITHUB_REPOSITORY must be owner/repository");
  }
  return { owner: parts[0], name: parts[1], full: configured };
}

function apiUrl(env, path) {
  const base = String(env.GITHUB_API_URL || "https://api.github.com").replace(/\/$/, "");
  return `${base}${path}`;
}

function headers(env, includeJson = false) {
  const token = String(env.GITHUB_TOKEN || "").trim();
  const value = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": API_VERSION,
    "User-Agent": "stock-data-pipeline-market-close-watchdog",
  };
  if (token) value.Authorization = `Bearer ${token}`;
  if (includeJson) value["Content-Type"] = "application/json";
  return value;
}

async function githubRequest(env, path, init = {}) {
  if (!String(env.GITHUB_TOKEN || "").trim()) {
    return { ok: false, status: 0, error: "EXTERNAL_TOKEN_MISSING" };
  }
  let last = { ok: false, status: 0, error: "GITHUB_API_UNAVAILABLE" };
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(apiUrl(env, path), {
        ...init,
        headers: { ...headers(env, Boolean(init.body)), ...(init.headers || {}) },
      });
      const text = await response.text();
      let body = null;
      try { body = text ? JSON.parse(text) : null; } catch { body = null; }
      if (response.ok) return { ok: true, status: response.status, body };
      last = {
        ok: false,
        status: response.status,
        error: `GITHUB_API_HTTP_${response.status}`,
        body: body && typeof body === "object" ? body : undefined,
      };
      if (!RETRYABLE.has(response.status) || attempt === 2) return last;
      const retryAfter = Number(response.headers.get("Retry-After") || 0);
      const delay = Math.min(5000, retryAfter > 0 ? retryAfter * 1000 : 500 * (2 ** attempt));
      await new Promise((resolve) => setTimeout(resolve, delay));
    } catch (error) {
      last = { ok: false, status: 0, error: String(error).slice(0, 240) };
      if (attempt === 2) return last;
      await new Promise((resolve) => setTimeout(resolve, 500 * (2 ** attempt)));
    }
  }
  return last;
}

function recentRun(runs, nowMs) {
  const values = Array.isArray(runs) ? runs : [];
  const cutoff = nowMs - LOOKBACK_MS;
  return values
    .filter((run) => {
      const created = Date.parse(String(run?.created_at || ""));
      return Number.isFinite(created) && created >= cutoff;
    })
    .sort((left, right) => Date.parse(String(right.created_at)) - Date.parse(String(left.created_at)))[0] || null;
}

export async function reconcileWorkflow(env, { market, kind, now = new Date() }) {
  const normalizedMarket = String(market || "").trim().toUpperCase();
  const workflowKind = String(kind || "").trim().toUpperCase();
  if (!WORKFLOWS[normalizedMarket]?.[workflowKind]) {
    return { status: "INVALID_ROUTE", market: normalizedMarket, kind: workflowKind };
  }
  const repo = repository(env);
  const workflow = WORKFLOWS[normalizedMarket][workflowKind];
  const encodedWorkflow = encodeURIComponent(workflow);
  const runsPath = `/repos/${repo.owner}/${repo.name}/actions/workflows/${encodedWorkflow}/runs?branch=${encodeURIComponent(String(env.GITHUB_REF || "main"))}&per_page=20`;
  const listing = await githubRequest(env, runsPath);
  const run = listing.ok ? recentRun(listing.body?.workflow_runs, now.getTime()) : null;
  const activeOrSuccessful = run && (
    ["queued", "in_progress", "waiting", "requested", "pending"].includes(String(run.status)) ||
    (String(run.status) === "completed" && String(run.conclusion) === "success")
  );
  const base = {
    market: normalizedMarket,
    kind: workflowKind,
    workflow,
    repository: repo.full,
    recent_run_id: run?.id || null,
    recent_run_status: run?.status || null,
    recent_run_conclusion: run?.conclusion || null,
  };
  if (activeOrSuccessful) {
    return { ...base, status: "NOOP_PRIMARY_ACTIVE_OR_SUCCESS" };
  }

  const dispatchPath = `/repos/${repo.owner}/${repo.name}/actions/workflows/${encodedWorkflow}/dispatches`;
  const dispatch = await githubRequest(env, dispatchPath, {
    method: "POST",
    body: JSON.stringify({ ref: String(env.GITHUB_REF || "main"), inputs: {} }),
  });
  return {
    ...base,
    status: dispatch.ok ? "DISPATCHED_RECONCILIATION" : "DISPATCH_FAILED",
    dispatch_http_status: dispatch.status,
    dispatch_error: dispatch.ok ? null : dispatch.error,
    status_check_error: listing.ok ? null : listing.error,
  };
}

export async function reconcileRoute(env, route, now = new Date()) {
  const results = [];
  for (const kind of route.kinds || []) {
    results.push(await reconcileWorkflow(env, { market: route.market, kind, now }));
  }
  return {
    worker: "market-close-watchdog",
    trigger: "CLOUDFLARE_CRON_FALLBACK",
    route,
    results,
  };
}

export default {
  async scheduled(controller, env) {
    const route = CRON_ROUTES[String(controller.cron || "")];
    const result = route
      ? await reconcileRoute(env, route, new Date())
      : { worker: "market-close-watchdog", status: "UNKNOWN_CRON", cron: controller.cron };
    // Never include request headers or environment values in the diagnostic.
    console.log(JSON.stringify(result));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const market = String(url.searchParams.get("market") || "").toUpperCase();
    const kind = String(url.searchParams.get("kind") || "D1_PROSPECTIVE").toUpperCase();
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ status: "READY", worker: "market-close-watchdog" }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    const result = await reconcileWorkflow(env, { market, kind, now: new Date() });
    return new Response(JSON.stringify(result), {
      status: result.status === "DISPATCH_FAILED" ? 502 : 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};
