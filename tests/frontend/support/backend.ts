import { vi } from "vitest";

export const BACKEND = "http://localhost:8000";

export type Reply = { status?: number; json?: unknown; body?: BodyInit | null; headers?: Record<string, string> };

export type BackendCall = {
  method: string;
  /** pathname + search, e.g. "/api/topics/a%20b/tags?tag=x" */
  path: string;
  url: string;
  /** parsed JSON body, the FormData for uploads, or undefined */
  body: unknown;
  init: RequestInit | undefined;
};

type Handler = Reply | ((call: BackendCall) => Reply | Promise<Reply>);

/**
 * Stands in for the FastAPI backend at the network boundary (global fetch). Routes are keyed "METHOD /path"
 * (the path without the query string); unmatched requests answer 500 so a wrong URL fails loudly.
 */
export function fakeBackend(routes: Record<string, Handler> = {}) {
  const calls: BackendCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const parsed = new URL(url);
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    else if (init?.body !== undefined && init?.body !== null) body = init.body;
    const call: BackendCall = { method, path: parsed.pathname + parsed.search, url, body, init };
    calls.push(call);

    const handler = routes[`${method} ${parsed.pathname}`];
    const reply: Reply = handler === undefined
      ? { status: 500, json: { detail: `fakeBackend: no route for ${method} ${parsed.pathname}` } }
      : typeof handler === "function" ? await handler(call) : handler;
    return toResponse(reply);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetch: fetchMock, last: () => calls[calls.length - 1] };
}

function toResponse({ status = 200, json, body, headers }: Reply): Response {
  if (status === 204) return new Response(null, { status });
  if (json !== undefined) {
    return new Response(JSON.stringify(json), { status, headers: { "Content-Type": "application/json", ...headers } });
  }
  return new Response(body ?? null, { status, headers });
}

/** Runs a server action that is expected to call redirect() and returns the redirect target. */
export async function redirectOf(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
  } catch (error) {
    const url = (error as { redirectUrl?: string }).redirectUrl;
    if (url !== undefined) return url;
    throw error;
  }
  throw new Error("expected a redirect");
}

export function form(fields: Record<string, string | Blob>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}
