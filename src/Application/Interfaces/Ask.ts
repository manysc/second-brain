import type { AskEvent, AskModel, EffortLevel, Turn } from "../DTOs/Ask";

export type AskAgentRequest = {
  prompt: string;
  systemPrompt: string;
  /** Tool names the agent may call, and the ones it must never call (bare names, e.g. "brain_search_items"). */
  allowedTools: readonly string[];
  forbiddenTools: readonly string[];
  maxTurns: number;
  model?: string;
  effort?: EffortLevel;
  /** Continue this earlier conversation instead of starting a new one. */
  resumeSessionId?: string;
  signal: AbortSignal;
};

/**
 * The agent that answers questions with the brain tools. It yields what happens as it happens: a "meta" event
 * once the conversation has an id, "text" as the answer streams, "tool" for each tool call and "error" when the
 * run ends early. It never yields "done"; that is the caller's to add.
 */
export interface AskAgent {
  ask(request: AskAgentRequest): AsyncIterable<AskEvent>;
}

export type StoredSession = {
  sessionId: string;
  customTitle?: string;
  summary?: string;
  firstPrompt?: string;
  lastModified: number;
};

/**
 * Past ask conversations. Only conversations the ask flow issued itself are visible here: an id that was never
 * issued (including any other session on the machine) is treated as not existing.
 */
export interface AskSessionStore {
  /** Makes sure the place conversations live in exists before one is started. */
  prepare(): void;
  isIssued(sessionId: string): boolean;
  issue(sessionId: string): void;
  list(limit: number): Promise<StoredSession[]>;
  turns(sessionId: string): Promise<Turn[]>;
  delete(sessionId: string): Promise<void>;
}

export interface ModelCatalog {
  list(): Promise<AskModel[]>;
}
