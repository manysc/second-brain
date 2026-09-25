import { rmSync } from "node:fs";
import { deleteSession, getSessionMessages } from "@anthropic-ai/claude-agent-sdk";
import { SESSION_CWD, isIssued, issuedMarker, toTurns } from "@/lib/ask-sessions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Only ids the ask route issued may be read or deleted; anything else (including real Claude Code sessions, which
// the SDK would otherwise resolve across projects) is reported as not found.
const notFound = () => Response.json({ error: "Conversation not found." }, { status: 404 });

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isIssued(id)) return notFound();
  try {
    const messages = await getSessionMessages(id, { dir: SESSION_CWD });
    return Response.json({ turns: toTurns(messages) }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Could not load conversation." },
      { status: 500 },
    );
  }
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isIssued(id)) return notFound();
  try {
    await deleteSession(id, { dir: SESSION_CWD });
    rmSync(issuedMarker(id), { force: true });
    return Response.json({ ok: true });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Could not delete conversation." },
      { status: 500 },
    );
  }
}
