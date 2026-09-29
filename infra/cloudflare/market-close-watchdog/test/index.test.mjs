import test from "node:test";
import assert from "node:assert/strict";

import {
  CRON_ROUTES,
  WORKFLOWS,
  reconcileWorkflow,
} from "../src/index.mjs";
import worker from "../src/index.mjs";

const ENV = {
  GITHUB_TOKEN: "fixture-token-never-logged",
  GITHUB_REPOSITORY: "EFSing/stock-data-pipeline",
  GITHUB_REF: "main",
  WATCHDOG_SMOKE_TOKEN: "fixture-smoke-token-never-logged",
};

function jsonResponse(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

test("successful primary run is a no-op and does not dispatch", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({ workflow_runs: [{
      id: 123,
      status: "completed",
      conclusion: "success",
      created_at: "2026-09-29T10:45:00Z",
    }] });
  };
  try {
    const result = await reconcileWorkflow(ENV, {
      market: "CN",
      kind: "D1_PROSPECTIVE",
      now: new Date("2026-09-29T10:55:00Z"),
    });
    assert.equal(result.status, "NOOP_PRIMARY_ACTIVE_OR_SUCCESS");
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test("missing primary run dispatches the same reconciliation workflow", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (request, init) => {
    requests.push({ request, init });
    if (requests.length === 1) return jsonResponse({ workflow_runs: [] });
    return new Response(null, { status: 204 });
  };
  try {
    const result = await reconcileWorkflow(ENV, {
      market: "US",
      kind: "DAILY_REPORT",
      now: new Date("2026-09-29T01:15:00Z"),
    });
    assert.equal(result.status, "DISPATCHED_RECONCILIATION");
    assert.equal(requests.length, 2);
    assert.equal(JSON.parse(requests[1].init.body).ref, "main");
    assert.match(String(requests[1].request), /us-daily-report\.yml/);
  } finally {
    globalThis.fetch = original;
  }
});

test("rate-limit retry is bounded and can observe the primary run", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    if (calls === 1) return jsonResponse({ message: "rate limit" }, 429, { "Retry-After": "0" });
    return jsonResponse({ workflow_runs: [{
      id: 124,
      status: "in_progress",
      created_at: "2026-09-29T10:50:00Z",
    }] });
  };
  try {
    const result = await reconcileWorkflow(ENV, {
      market: "CN",
      kind: "DAILY_REPORT",
      now: new Date("2026-09-29T10:55:00Z"),
    });
    assert.equal(result.status, "NOOP_PRIMARY_ACTIVE_OR_SUCCESS");
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = original;
  }
});

test("missing token is fail-closed and never calls GitHub", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return jsonResponse({}); };
  try {
    const result = await reconcileWorkflow(
      { ...ENV, GITHUB_TOKEN: "" },
      { market: "CN", kind: "DAILY_REPORT", now: new Date() },
    );
    assert.equal(result.status, "DISPATCH_FAILED");
    assert.equal(result.dispatch_error, "EXTERNAL_TOKEN_MISSING");
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = original;
  }
});

test("manual HTTP smoke endpoint requires its independent token", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return jsonResponse({}); };
  try {
    const response = await worker.fetch(new Request(
      "https://watchdog.example/?market=CN&kind=D1_PROSPECTIVE",
      { method: "POST" },
    ), ENV);
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { status: "SMOKE_TOKEN_REQUIRED" });
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = original;
  }
});

test("authorized HTTP smoke endpoint dispatches only the repository workflow", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (request, init) => {
    requests.push({ request, init });
    if (requests.length === 1) return jsonResponse({ workflow_runs: [] });
    return new Response(null, { status: 204 });
  };
  try {
    const response = await worker.fetch(new Request(
      "https://watchdog.example/?market=CN&kind=D1_PROSPECTIVE",
      { method: "POST", headers: { Authorization: "Bearer fixture-smoke-token-never-logged" } },
    ), ENV);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).status, "DISPATCHED_RECONCILIATION");
    assert.equal(requests.length, 2);
    assert.match(String(requests[1].request), /setup01-d1-vps-natural-collector-cn\.yml/);
    assert.doesNotMatch(JSON.stringify(requests[1].init), /fixture-smoke-token/);
  } finally {
    globalThis.fetch = original;
  }
});

test("routes preserve independent CN/US daily and D1 workflow identities", () => {
  assert.equal(WORKFLOWS.CN.DAILY_REPORT, "cn-daily-report.yml");
  assert.equal(WORKFLOWS.US.D1_PROSPECTIVE, "setup01-d1-vps-natural-collector-us.yml");
  assert.deepEqual(CRON_ROUTES["55 10 * * 1-5"], {
    market: "CN",
    kinds: ["D1_PROSPECTIVE"],
  });
});
