import { listSessions } from "@anthropic-ai/claude-agent-sdk";
import { SESSION_CWD, isIssued, type SessionSummary } from "@/lib/ask-sessions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const listed = await listSessions({ dir: SESSION_CWD, includeWorktrees: false, limit: 50 });
    const sessions: SessionSummary[] = listed
      .filter((session) => isIssued(session.sessionId))
      .map((session) => ({
        sessionId: session.sessionId,
        title: session.customTitle || session.summary || session.firstPrompt || "Untitled conversation",
        lastModified: session.lastModified,
      }));
    return Response.json({ sessions }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Could not load history." },
      { status: 500 },
    );
  }
}
