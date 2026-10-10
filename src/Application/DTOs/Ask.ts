export const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const;
export type EffortLevel = (typeof EFFORT_LEVELS)[number];

/** A model the connected account can use. The catalog passes its provider's entry through unchanged. */
export type AskModel = {
  value: string;
  displayName: string;
  description?: string;
  resolvedModel?: string;
  supportsEffort?: boolean;
  supportedEffortLevels?: EffortLevel[];
};

export type AskEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "meta"; model: string; effort: string | null; sessionId: string }
  | { type: "done" }
  | { type: "error"; message: string };

export type ToolCall = { name: string; input: unknown };

export type Turn = {
  id: number;
  prompt: string;
  answer: string;
  tools: ToolCall[];
  usedModel: string | null;
  usedEffort: string | null;
  error: string | null;
  running: boolean;
};

export type SessionSummary = { sessionId: string; title: string; lastModified: number };

/** What the ask endpoint received, before validation. `null` when the body could not be read at all. */
export type AskInput = { prompt?: unknown; model?: unknown; effort?: unknown; sessionId?: unknown } | null;

export type AskOutcome =
  | { ok: false; status: 400 | 410; error: string }
  | { ok: true; events: AsyncIterable<AskEvent> };
