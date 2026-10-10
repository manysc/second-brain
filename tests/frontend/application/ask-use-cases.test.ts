// @vitest-environment node
// The ask flow against in-memory ports: what is validated, which conversations may be touched, the read-only tool
// policy handed to the agent, and how a run is reported. No Agent SDK and no file system.
import { describe, expect, it, vi } from "vitest";
import type { AskEvent, AskModel, Turn } from "@/Application/DTOs/Ask";
import { NotFoundError } from "@/Application/Errors";
import type { AskAgent, AskAgentRequest, AskSessionStore, StoredSession } from "@/Application/Interfaces/Ask";
import { READ_TOOLS, SYSTEM_PROMPT, WRITE_TOOLS, askUseCases, parseEffort, parseModel } from "@/Application/UseCases/ask";

const SESSION = "0f8fad5b-d9cb-469f-a165-70867728950e";
const EXPIRED = "This conversation has expired. Start a new conversation.";

class FakeAgent implements AskAgent {
  requests: AskAgentRequest[] = [];
  constructor(private readonly script: (AskEvent | Error)[] = []) {}

  async *ask(request: AskAgentRequest): AsyncGenerator<AskEvent> {
    this.requests.push(request);
    for (const step of this.script) {
      if (step instanceof Error) throw step;
      yield step;
    }
  }
}

class FakeSessions implements AskSessionStore {
  issued = new Set<string>();
  prepared = 0;
  stored: StoredSession[] = [];
  transcripts = new Map<string, Turn[]>();

  prepare() {
    this.prepared += 1;
  }
  isIssued(sessionId: string) {
    return this.issued.has(sessionId);
  }
  issue(sessionId: string) {
    this.issued.add(sessionId);
  }
  async list(limit: number) {
    return this.stored.slice(0, limit);
  }
  async turns(sessionId: string) {
    return this.transcripts.get(sessionId) ?? [];
  }
  async delete(sessionId: string) {
    this.issued.delete(sessionId);
  }
}

function setup(script: (AskEvent | Error)[] = [], models: AskModel[] = []) {
  const agent = new FakeAgent(script);
  const sessions = new FakeSessions();
  const catalog = { list: vi.fn(async () => models) };
  return { agent, sessions, catalog, ask: askUseCases(agent, sessions, catalog) };
}

async function collect(events: AsyncIterable<AskEvent>): Promise<AskEvent[]> {
  const collected: AskEvent[] = [];
  for await (const event of events) collected.push(event);
  return collected;
}

const live = () => new AbortController().signal;

describe("asking a question", () => {
  it.each([
    [null, "prompt is required"],
    [{}, "prompt is required"],
    [{ prompt: 7 }, "prompt is required"],
    [{ prompt: "  " }, "prompt is required"],
    [{ prompt: "x".repeat(2001) }, "prompt exceeds 2000 characters"],
    [{ prompt: "hi", sessionId: "../../etc" }, "sessionId must be a UUID"],
    [{ prompt: "hi", sessionId: 42 }, "sessionId must be a UUID"],
  ])("refuses %j", (input, error) => {
    const { ask, agent, sessions } = setup();
    expect(ask.askQuestion(input, live())).toEqual({ ok: false, status: 400, error });
    expect(agent.requests).toHaveLength(0);
    expect(sessions.prepared).toBe(0);
  });

  it("refuses to resume a conversation it did not issue, without calling the agent", () => {
    const { ask, agent } = setup();
    expect(ask.askQuestion({ prompt: "hi", sessionId: SESSION }, live())).toEqual({ ok: false, status: 410, error: EXPIRED });
    expect(agent.requests).toHaveLength(0);
  });

  it("gives the agent the read tools only and adds done after a clean run", async () => {
    const { ask, agent, sessions } = setup([
      { type: "meta", model: "claude-opus-5-5", effort: "high", sessionId: SESSION },
      { type: "text", text: "Answer" },
    ]);
    const signal = live();
    const outcome = ask.askQuestion({ prompt: " What changed? ", model: " opus ", effort: "high" }, signal);
    if (!outcome.ok) throw new Error(outcome.error);
    expect(sessions.isIssued(SESSION)).toBe(false); // nothing runs until the events are read
    expect(await collect(outcome.events)).toEqual([
      { type: "meta", model: "claude-opus-5-5", effort: "high", sessionId: SESSION },
      { type: "text", text: "Answer" },
      { type: "done" },
    ]);
    expect(sessions.isIssued(SESSION)).toBe(true);
    expect(agent.requests).toEqual([
      {
        prompt: "What changed?",
        systemPrompt: SYSTEM_PROMPT,
        allowedTools: READ_TOOLS,
        forbiddenTools: WRITE_TOOLS,
        maxTurns: 12,
        model: "opus",
        effort: "high",
        resumeSessionId: undefined,
        signal,
      },
    ]);
    expect(READ_TOOLS.filter((tool) => (WRITE_TOOLS as readonly string[]).includes(tool))).toEqual([]);
  });

  it("resumes an issued conversation and drops unusable model and effort values", async () => {
    const { ask, agent, sessions } = setup();
    sessions.issue(SESSION);
    const outcome = ask.askQuestion({ prompt: "more", sessionId: SESSION, model: "m".repeat(101), effort: "turbo" }, live());
    if (!outcome.ok) throw new Error(outcome.error);
    expect(await collect(outcome.events)).toEqual([{ type: "done" }]);
    expect(agent.requests[0]).toMatchObject({ resumeSessionId: SESSION, model: undefined, effort: undefined });
  });

  it("reports a failed run as an error event instead of done", async () => {
    const failed = setup([{ type: "text", text: "par" }, new Error("spawn failed")]);
    const outcome = failed.ask.askQuestion({ prompt: "hi" }, live());
    if (!outcome.ok) throw new Error(outcome.error);
    expect(await collect(outcome.events)).toEqual([
      { type: "text", text: "par" },
      { type: "error", message: "spawn failed" },
    ]);
  });

  it("explains a vanished transcript as an expired conversation, a timeout as a timeout and any other abort as a cancel", async () => {
    const gone = setup([new Error("No conversation found with session ID")]);
    gone.sessions.issue(SESSION);
    const expired = gone.ask.askQuestion({ prompt: "hi", sessionId: SESSION }, live());
    if (!expired.ok) throw new Error(expired.error);
    expect(await collect(expired.events)).toEqual([{ type: "error", message: EXPIRED }]);

    const timeout = new AbortController();
    timeout.abort(new DOMException("slow", "TimeoutError"));
    const timedOut = setup([new Error("aborted")]).ask.askQuestion({ prompt: "hi" }, timeout.signal);
    if (!timedOut.ok) throw new Error(timedOut.error);
    expect(await collect(timedOut.events)).toEqual([
      { type: "error", message: "The request timed out. Try a narrower question, or ask again." },
    ]);

    const abort = new AbortController();
    abort.abort();
    const cancelled = setup([new Error("aborted")]).ask.askQuestion({ prompt: "hi" }, abort.signal);
    if (!cancelled.ok) throw new Error(cancelled.error);
    expect(await collect(cancelled.events)).toEqual([{ type: "error", message: "The request was cancelled." }]);
  });
});

describe("past conversations", () => {
  it("titles each conversation from the best text available", async () => {
    const { ask, sessions } = setup();
    sessions.stored = [
      { sessionId: "a", customTitle: "Named", summary: "s", firstPrompt: "p", lastModified: 3 },
      { sessionId: "b", summary: "Summary", firstPrompt: "p", lastModified: 2 },
      { sessionId: "c", firstPrompt: "First question", lastModified: 1 },
      { sessionId: "d", lastModified: 0 },
    ];
    expect(await ask.listAskSessions()).toEqual([
      { sessionId: "a", title: "Named", lastModified: 3 },
      { sessionId: "b", title: "Summary", lastModified: 2 },
      { sessionId: "c", title: "First question", lastModified: 1 },
      { sessionId: "d", title: "Untitled conversation", lastModified: 0 },
    ]);
  });

  it("reads and deletes only conversations it issued", async () => {
    const { ask, sessions } = setup();
    await expect(ask.getAskSession(SESSION)).rejects.toThrow(new NotFoundError("Conversation not found."));
    await expect(ask.deleteAskSession(SESSION)).rejects.toBeInstanceOf(NotFoundError);

    sessions.issue(SESSION);
    const turns = [{ id: 1, prompt: "q" } as Turn];
    sessions.transcripts.set(SESSION, turns);
    expect(await ask.getAskSession(SESSION)).toBe(turns);
    await ask.deleteAskSession(SESSION);
    expect(sessions.isIssued(SESSION)).toBe(false);
  });
});

describe("models", () => {
  it("lists what the catalog reports", async () => {
    const models = [{ value: "default", displayName: "Default" }];
    expect(await setup([], models).ask.listAskModels()).toBe(models);
  });

  it("accepts only a trimmed, reasonably short model name and a known effort level", () => {
    expect(parseModel("  opus ")).toBe("opus");
    expect(parseModel("")).toBeUndefined();
    expect(parseModel("m".repeat(101))).toBeUndefined();
    expect(parseModel(5)).toBeUndefined();
    expect(parseEffort("xhigh")).toBe("xhigh");
    expect(parseEffort("HIGH")).toBeUndefined();
    expect(parseEffort(null)).toBeUndefined();
  });
});
