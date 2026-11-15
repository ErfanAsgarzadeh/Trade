import test from "node:test";
import assert from "node:assert/strict";
import { ApiClient, ApiError, SessionChanged, needsTwoFactor } from "./api";

test("same-origin cookies and CSRF accompany mutations; no client auth storage", async () => {
  let captured: RequestInit | undefined;
  const client = new ApiClient(async (_url, init) => {
    captured = init;
    return Response.json({ status: "saved" });
  });
  client.csrf = "session-csrf";
  await client.request("/api/me/connection", "PUT", { market: "spot" });
  assert.equal(captured?.credentials, "same-origin");
  assert.equal(captured?.cache, "no-store");
  assert.equal(
    (captured?.headers as Record<string, string>)["X-CSRF-Token"],
    "session-csrf",
  );
  assert.deepEqual(JSON.parse(captured?.body as string), { market: "spot" });
});

test("a delayed response from a logged-out session is discarded, even if transport ignores abort", async () => {
  let resolve!: (response: Response) => void;
  const client = new ApiClient(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const pending = client.request("/api/me/connection");
  const rejected = assert.rejects(pending, SessionChanged);
  client.invalidate();
  resolve(Response.json({ balances: ["private old account"] }));
  await rejected;
});

test("session expiry clears CSRF, aborts other work and notifies the UI", async () => {
  let notified = false;
  const client = new ApiClient(async () =>
    Response.json({ detail: "secret must not be echoed" }, { status: 401 }),
  );
  client.csrf = "expired";
  client.onUnauthorized = () => {
    notified = true;
  };
  await assert.rejects(
    client.request("/api/me"),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 401 &&
      !error.message.includes("secret"),
  );
  assert.equal(client.csrf, "");
  assert.equal(notified, true);
});

test("the server's detail text selects the message for two-step login and password answers", () => {
  const detail = new ApiError(403, "Two-factor setup required");
  assert.equal(detail.status, 403);
  assert.equal(detail.detail, "Two-factor setup required");
  assert.match(detail.message, /ورود دومرحله‌ای/);
  assert.notEqual(detail.message, new ApiError(403).message);
  assert.equal(
    new ApiError(403, "something else").message,
    new ApiError(403).message,
  );
});

test("a login answer asking for the code is told apart from wrong credentials", async () => {
  const client = new ApiClient(async () =>
    Response.json({ detail: "Two-factor code required" }, { status: 401 }),
  );
  await assert.rejects(client.request("/api/login", "POST", {}), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(needsTwoFactor(error), true);
    assert.equal(
      needsTwoFactor(new ApiError(401, "Invalid credentials")),
      false,
    );
    return true;
  });
});
