import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { deleteSession, getSessionMessages, listSessions } from "@anthropic-ai/claude-agent-sdk";
import type { SessionMessage } from "@anthropic-ai/claude-agent-sdk";
import type { Turn } from "@/Application/DTOs/Ask";
import type { AskSessionStore, StoredSession } from "@/Application/Interfaces/Ask";
import { UUID } from "@/Domain";

export const MCP_SERVER = "brain-assistant";
export const MCP_TOOL_PREFIX = `mcp__${MCP_SERVER}__`;

// Ask conversations run from their own working directory so their transcripts stay out of the repo's Claude Code
// session list. That does NOT stop a client from resuming other sessions: the SDK resolves a session id across all
// projects (and appends to that transcript). So only ids the ask flow issued are accepted: each one gets a marker
// file under SESSION_CWD, and a resume, read or delete without a marker is refused before the SDK is ever called.
export const SESSION_CWD = path.join(os.tmpdir(), "second-brain-ask");
export const ISSUED_DIR = path.join(SESSION_CWD, "issued");

export function issuedMarker(sessionId: string): string {
  return path.join(ISSUED_DIR, sessionId);
}

type Block = { type?: string; text?: string; name?: string; input?: unknown };

function blocksOf(message: unknown): { blocks: Block[]; model: string | null } {
  const body = (message ?? {}) as { content?: unknown; model?: unknown };
  const content = body.content;
  const blocks: Block[] =
    typeof content === "string" ? [{ type: "text", text: content }] : Array.isArray(content) ? (content as Block[]) : [];
  return { blocks, model: typeof body.model === "string" ? body.model : null };
}

// Rebuilds the client's turns from a raw transcript: a user message with text starts a turn (tool_result-only user
// messages are the SDK feeding tool output back and are skipped); the assistant messages that follow fill in the answer.
export function toTurns(messages: SessionMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (const message of messages) {
    if (message.parent_tool_use_id !== null || message.parent_agent_id) continue;
    const { blocks, model } = blocksOf(message.message);
    if (message.type === "user") {
      const prompt = blocks
        .filter((block) => block.type === "text")
        .map((block) => block.text ?? "")
        .join("\n")
        .trim();
      if (!prompt) continue;
      turns.push({
        id: turns.length + 1,
        prompt,
        answer: "",
        tools: [],
        usedModel: null,
        usedEffort: null,
        error: null,
        running: false,
      });
    } else if (message.type === "assistant") {
      const turn = turns[turns.length - 1];
      if (!turn) continue;
      if (model && !turn.usedModel) turn.usedModel = model;
      for (const block of blocks) {
        if (block.type === "text" && block.text) turn.answer += block.text;
        else if (block.type === "tool_use" && block.name) {
          turn.tools.push({ name: block.name.replace(MCP_TOOL_PREFIX, ""), input: block.input });
        }
      }
    }
  }
  return turns;
}

/** Ask conversations: marker files on disk say which ones this app issued; the transcripts live with the SDK. */
export class FsAskSessionStore implements AskSessionStore {
  prepare(): void {
    mkdirSync(ISSUED_DIR, { recursive: true });
  }

  isIssued(sessionId: string): boolean {
    return UUID.test(sessionId) && existsSync(issuedMarker(sessionId));
  }

  issue(sessionId: string): void {
    writeFileSync(issuedMarker(sessionId), "");
  }

  async list(limit: number): Promise<StoredSession[]> {
    const listed = await listSessions({ dir: SESSION_CWD, includeWorktrees: false, limit });
    return listed
      .filter((session) => this.isIssued(session.sessionId))
      .map((session) => ({
        sessionId: session.sessionId,
        customTitle: session.customTitle,
        summary: session.summary,
        firstPrompt: session.firstPrompt,
        lastModified: session.lastModified,
      }));
  }

  async turns(sessionId: string): Promise<Turn[]> {
    return toTurns(await getSessionMessages(sessionId, { dir: SESSION_CWD }));
  }

  async delete(sessionId: string): Promise<void> {
    await deleteSession(sessionId, { dir: SESSION_CWD });
    rmSync(issuedMarker(sessionId), { force: true });
  }
}
