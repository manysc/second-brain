// HTTP handlers behind src/app/api/ask/*: they turn requests into ask use-case calls and results into responses.
import type { AskInput } from "@/Application/DTOs/Ask";
import { NotFoundError } from "@/Application/Errors";
import { useCases } from "@/composition";

const TIMEOUT_MS = 120_000;
const NO_STORE = { "Cache-Control": "no-store" };

type IdParams = { params: Promise<{ id: string }> };

/** POST /api/ask: answers as newline-delimited JSON events while the agent works. */
export async function postAsk(request: Request): Promise<Response> {
  // an unreadable body is treated like an empty one, so it fails the prompt check below
  const input = (await request.json().catch(() => null)) as AskInput;

  const abort = new AbortController();
  const outcome = useCases.askQuestion(input, abort.signal);
  if (!outcome.ok) return Response.json({ error: outcome.error }, { status: outcome.status });

  const timeout = setTimeout(() => abort.abort(), TIMEOUT_MS);
  request.signal.addEventListener("abort", () => abort.abort());

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const event of outcome.events) {
          controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
        }
      } finally {
        clearTimeout(timeout);
        controller.close();
      }
    },
    cancel() {
      abort.abort();
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8", ...NO_STORE },
  });
}

function failure(error: unknown, fallback: string): Response {
  if (error instanceof NotFoundError) return Response.json({ error: error.message }, { status: 404 });
  return Response.json({ error: error instanceof Error ? error.message : fallback }, { status: 500 });
}

/** GET /api/ask/sessions: past conversations this app started. */
export async function getAskSessions(): Promise<Response> {
  try {
    return Response.json({ sessions: await useCases.listAskSessions() }, { headers: NO_STORE });
  } catch (error) {
    return failure(error, "Could not load history.");
  }
}

/** GET /api/ask/sessions/[id]: one conversation, as the turns the client renders. */
export async function getAskSession(_request: Request, { params }: IdParams): Promise<Response> {
  const { id } = await params;
  try {
    return Response.json({ turns: await useCases.getAskSession(id) }, { headers: NO_STORE });
  } catch (error) {
    return failure(error, "Could not load conversation.");
  }
}

/** DELETE /api/ask/sessions/[id] */
export async function deleteAskSession(_request: Request, { params }: IdParams): Promise<Response> {
  const { id } = await params;
  try {
    await useCases.deleteAskSession(id);
    return Response.json({ ok: true });
  } catch (error) {
    return failure(error, "Could not delete conversation.");
  }
}

/** GET /api/ask/models: what the connected account can use. Listing is slow, so pages also warm it up front. */
export async function getAskModels(): Promise<Response> {
  try {
    return Response.json({ models: await useCases.listAskModels() });
  } catch (error) {
    console.error("supportedModels() failed:", error);
    return Response.json({ models: [], error: "Model list unavailable." }, { status: 503 });
  }
}
