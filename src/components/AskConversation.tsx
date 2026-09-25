"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { EffortLevel, ModelInfo } from "@anthropic-ai/claude-agent-sdk";

type ToolCall = { name: string; input: unknown };
type Turn = {
  id: number;
  prompt: string;
  answer: string;
  tools: ToolCall[];
  usedModel: string | null;
  usedEffort: string | null;
  error: string | null;
  running: boolean;
};
type AskEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "meta"; model: string; effort: string | null; sessionId: string }
  | { type: "done" }
  | { type: "error"; message: string };

// Bounds the cost of one conversation; the server also caps each request.
const MAX_CONVERSATION_TURNS = 20;

// Effort options are never hardcoded: they come from the live "default" model entry (or the union
// of whatever models are known) so the picker always reflects what the connected account actually supports.
function effortLevelsFor(model: ModelInfo | undefined, allModels: ModelInfo[]): EffortLevel[] {
  if (model) return model.supportedEffortLevels ?? [];
  const defaultEntry = allModels.find((m) => m.value === "default");
  if (defaultEntry) return defaultEntry.supportedEffortLevels ?? [];
  return Array.from(new Set(allModels.flatMap((m) => m.supportedEffortLevels ?? [])));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CITATION = /\[([A-Za-z0-9_.:-]{1,200})\]/g;

// Record IDs are UUIDs for topics and "<meetingId>:<key>" for items; anything else is shown unlinked.
function citationHref(id: string): string | null {
  if (UUID.test(id)) return `/topics/${id}`;
  const meetingId = id.includes(":") ? id.split(":", 1)[0] : null;
  return meetingId ? `/meetings/${encodeURIComponent(meetingId)}` : null;
}

function withCitations(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION)) {
    const index = match.index ?? 0;
    if (index > last) nodes.push(text.slice(last, index));
    const href = citationHref(match[1]);
    nodes.push(
      href ? (
        <Link key={index} href={href} className="citation" title={match[1]}>[{match[1]}]</Link>
      ) : (
        <span key={index} className="citation" title={match[1]}>[{match[1]}]</span>
      ),
    );
    last = index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function AskConversation({
  initialQuery,
  prompts,
  initialModel,
  initialEffort,
}: {
  initialQuery: string;
  prompts: string[];
  initialModel?: string;
  initialEffort?: string;
}) {
  const router = useRouter();
  // The first turn is seeded from ?q= and started by the effect below; follow-ups are appended client-side so
  // the agent session (sessionIdRef) survives. Only the first prompt lives in the URL.
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>(() =>
    initialQuery
      ? [{ id: 1, prompt: initialQuery, answer: "", tools: [], usedModel: null, usedEffort: null, error: null, running: true }]
      : [],
  );
  const nextTurnId = useRef(initialQuery ? 1 : 0);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  // null = the model list hasn't loaded yet (listing models spawns the CLI, which can take many seconds).
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [modelsAttempt, setModelsAttempt] = useState(0);
  const [selectedModel, setSelectedModel] = useState(initialModel ?? "");
  const [selectedEffort, setSelectedEffort] = useState(initialEffort ?? "");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/ask/models");
        if (!response.ok) throw new Error(`Model list failed (${response.status}).`);
        const body = (await response.json()) as { models: ModelInfo[] };
        if (!cancelled) setModels(body.models);
      } catch {
        if (!cancelled) {
          setModels([]);
          setModelsError("Model list unavailable — using default.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modelsAttempt]);

  function retryModels() {
    setModelsError(null);
    setModels(null);
    setModelsAttempt((attempt) => attempt + 1);
  }

  const availableModels = models ?? [];
  const modelsLoading = models === null;
  const selectedModelInfo = availableModels.find((m) => m.value === selectedModel);
  const effortOptions = effortLevelsFor(selectedModelInfo, availableModels);
  // Absent selectedModelInfo (no model chosen yet, or a stale/unknown value) is treated as "unknown, allow it" —
  // only an explicitly-known model that omits/denies effort support disables the selector.
  const effortDisabled = modelsLoading || (selectedModelInfo !== undefined && !selectedModelInfo.supportsEffort);
  const effectiveEffort = effortDisabled || !effortOptions.includes(selectedEffort as EffortLevel) ? "" : selectedEffort;

  const updateTurn = useCallback((id: number, change: (turn: Turn) => Turn) => {
    setTurns((current) => current.map((turn) => (turn.id === id ? change(turn) : turn)));
  }, []);

  const runTurn = useCallback(
    async (id: number, prompt: string, model: string | undefined, effort: string | undefined, controller: AbortController) => {
      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt,
            model: model || undefined,
            effort: effort || undefined,
            sessionId: sessionIdRef.current ?? undefined,
          }),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          const body = (await response.json().catch(() => null)) as { error?: string } | null;
          throw new Error(body?.error ?? `Ask failed (${response.status}).`);
        }
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            // A superseded (strict-mode remount) or stopped run must not write into the transcript.
            if (!line.trim() || controller.signal.aborted) continue;
            const event = JSON.parse(line) as AskEvent;
            if (event.type === "text") updateTurn(id, (turn) => ({ ...turn, answer: turn.answer + event.text }));
            else if (event.type === "tool") {
              updateTurn(id, (turn) => ({ ...turn, tools: [...turn.tools, { name: event.name, input: event.input }] }));
            } else if (event.type === "meta") {
              sessionIdRef.current = event.sessionId;
              updateTurn(id, (turn) => ({ ...turn, usedModel: event.model, usedEffort: event.effort }));
            } else if (event.type === "error") updateTurn(id, (turn) => ({ ...turn, error: event.message }));
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          const message = caught instanceof Error ? caught.message : "Ask failed.";
          updateTurn(id, (turn) => ({ ...turn, error: message }));
        }
      } finally {
        // An aborted run was superseded or stopped; stop() already cleared its running flag.
        if (!controller.signal.aborted) updateTurn(id, (turn) => ({ ...turn, running: false }));
      }
    },
    [updateTurn],
  );

  useEffect(() => {
    if (!initialQuery) return;
    const controller = new AbortController();
    abortRef.current = controller;
    void runTurn(1, initialQuery, initialModel, initialEffort, controller);
    return () => controller.abort();
  }, [initialQuery, initialModel, initialEffort, runTurn]);

  const busy = turns.some((turn) => turn.running);
  const atLimit = turns.length >= MAX_CONVERSATION_TURNS;

  useEffect(() => {
    // Keep the newest follow-up in view; skip the initial load so the page doesn't jump.
    if (turns.length > 1) endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = draft.trim();
    if (!prompt || busy || atLimit) return;
    setDraft("");
    const controller = new AbortController();
    abortRef.current = controller;
    const id = ++nextTurnId.current;
    setTurns((current) => [
      ...current,
      { id, prompt, answer: "", tools: [], usedModel: null, usedEffort: null, error: null, running: true },
    ]);
    // While the list is still loading nothing can be validated yet, so keep whatever was chosen.
    void runTurn(id, prompt, selectedModel, modelsLoading ? selectedEffort : effectiveEffort, controller);
  }

  function stop() {
    abortRef.current?.abort();
    setTurns((current) => current.map((turn) => (turn.running ? { ...turn, running: false } : turn)));
  }

  function newConversation() {
    abortRef.current?.abort();
    sessionIdRef.current = null;
    nextTurnId.current = 0;
    setTurns([]);
    setDraft("");
    if (initialQuery) router.push("/ask");
  }

  function modelName(used: string | null) {
    if (!used) return null;
    return availableModels.find((m) => m.value === used || m.resolvedModel === used)?.displayName ?? used;
  }

  const composer = (
    <>
      <form className="ask-box" onSubmit={submit}>
        <textarea
          name="q"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder={turns.length ? "Ask a follow-up…" : "What should I follow up on?"}
          aria-label={turns.length ? "Follow-up question" : "Question"}
          disabled={atLimit}
        />
        {busy ? (
          <button type="button" onClick={stop}>Stop</button>
        ) : (
          <button type="submit" disabled={atLimit}>Ask <span>↗</span></button>
        )}
      </form>
      <div className="ask-options">
        <label>
          Model
          <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} disabled={modelsLoading}>
            <option value="">{modelsLoading ? "Loading models…" : "Default"}</option>
            {selectedModel && !selectedModelInfo && <option value={selectedModel}>{selectedModel}</option>}
            {availableModels.map((m) => (
              <option key={m.value} value={m.value}>{m.displayName}</option>
            ))}
          </select>
        </label>
        <label>
          Effort
          <select
            value={effectiveEffort}
            onChange={(e) => setSelectedEffort(e.target.value)}
            disabled={effortDisabled}
          >
            <option value="">Default</option>
            {effortOptions.map((level) => (
              <option key={level} value={level}>{level}</option>
            ))}
          </select>
        </label>
        {modelsError && (
          <span className="ask-options-note">
            {modelsError} <button type="button" className="ask-options-retry" onClick={retryModels}>Retry</button>
          </span>
        )}
        {turns.length > 0 && (
          <button type="button" className="ask-options-retry" onClick={newConversation}>New conversation</button>
        )}
      </div>
      {atLimit && (
        <p className="ask-error">
          This conversation reached {MAX_CONVERSATION_TURNS} questions. Start a new conversation to continue.
        </p>
      )}
    </>
  );

  return (
    <>
      {turns.length === 0 && composer}
      {turns.length === 0 && (
        <div className="prompt-row">
          {prompts.map((prompt) => (
            <a key={prompt} href={`/ask?q=${encodeURIComponent(prompt)}`}>{prompt}</a>
          ))}
        </div>
      )}
      {turns.map((turn) => {
        const usedModelName = modelName(turn.usedModel);
        return (
          <section key={turn.id} className="answer turn">
            <p className="eyebrow">Answer / cites record IDs, read-only</p>
            <h2>{turn.prompt}</h2>
            {usedModelName && (
              <p className="ask-meta">
                Answered with {usedModelName}
                {turn.usedEffort ? ` · ${turn.usedEffort} effort` : ""}
              </p>
            )}
            {turn.tools.length > 0 && (
              <details className="tool-trace">
                <summary>Tool activity ({turn.tools.length})</summary>
                <ol>
                  {turn.tools.map((tool, index) => (
                    <li key={index}><b>{tool.name}</b> <code>{JSON.stringify(tool.input)}</code></li>
                  ))}
                </ol>
              </details>
            )}
            {turn.answer ? (
              <div className="answer-text">
                {turn.answer.split("\n").map((line, index) => (
                  <Fragment key={index}>{withCitations(line)}<br /></Fragment>
                ))}
              </div>
            ) : turn.running ? (
              <p>Searching the brain…</p>
            ) : null}
            {turn.error && <p className="ask-error" role="alert">{turn.error}</p>}
          </section>
        );
      })}
      {turns.length > 0 && <div className="turn-composer">{composer}</div>}
      <div ref={endRef} />
    </>
  );
}
