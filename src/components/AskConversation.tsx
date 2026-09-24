"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useState, type FormEvent, type ReactNode } from "react";
import type { EffortLevel, ModelInfo } from "@anthropic-ai/claude-agent-sdk";

type ToolCall = { name: string; input: unknown };
type AskEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "meta"; model: string; effort: string | null }
  | { type: "done" }
  | { type: "error"; message: string };

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
  const [draft, setDraft] = useState(initialQuery);
  const [answer, setAnswer] = useState("");
  const [tools, setTools] = useState<ToolCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(Boolean(initialQuery));
  const [usedModel, setUsedModel] = useState<string | null>(null);
  const [usedEffort, setUsedEffort] = useState<string | null>(null);

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

  useEffect(() => {
    if (!initialQuery) return;
    const controller = new AbortController();
    (async () => {
      setUsedModel(null);
      setUsedEffort(null);
      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: initialQuery, model: initialModel || undefined, effort: initialEffort || undefined }),
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
            if (!line.trim()) continue;
            const event = JSON.parse(line) as AskEvent;
            if (event.type === "text") setAnswer((current) => current + event.text);
            else if (event.type === "tool") setTools((current) => [...current, { name: event.name, input: event.input }]);
            else if (event.type === "meta") {
              setUsedModel(event.model);
              setUsedEffort(event.effort);
            } else if (event.type === "error") setError(event.message);
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Ask failed.");
        }
      } finally {
        if (!controller.signal.aborted) setRunning(false);
      }
    })();
    return () => controller.abort();
  }, [initialQuery, initialModel, initialEffort]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = draft.trim();
    if (!q) return;
    const params = new URLSearchParams({ q });
    if (selectedModel) params.set("model", selectedModel);
    // While the list is still loading nothing can be validated yet, so keep whatever was chosen/carried in the URL.
    const effort = modelsLoading ? selectedEffort : effectiveEffort;
    if (effort) params.set("effort", effort);
    router.push(`/ask?${params.toString()}`);
  }

  const usedModelName = usedModel ? availableModels.find((m) => m.value === usedModel || m.resolvedModel === usedModel)?.displayName ?? usedModel : null;

  return (
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
          placeholder="What should I follow up on?"
          aria-label="Question"
        />
        <button type="submit" disabled={running}>Ask <span>↗</span></button>
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
      </div>
      <div className="prompt-row">
        {prompts.map((prompt) => (
          <a key={prompt} href={`/ask?q=${encodeURIComponent(prompt)}`}>{prompt}</a>
        ))}
      </div>
      {initialQuery && (
        <section className="answer">
          <p className="eyebrow">Answer / cites record IDs, read-only</p>
          <h2>{initialQuery}</h2>
          {usedModelName && (
            <p className="ask-meta">
              Answered with {usedModelName}
              {usedEffort ? ` · ${usedEffort} effort` : ""}
            </p>
          )}
          {tools.length > 0 && (
            <details className="tool-trace">
              <summary>Tool activity ({tools.length})</summary>
              <ol>
                {tools.map((tool, index) => (
                  <li key={index}><b>{tool.name}</b> <code>{JSON.stringify(tool.input)}</code></li>
                ))}
              </ol>
            </details>
          )}
          {answer ? (
            <div className="answer-text">
              {answer.split("\n").map((line, index) => (
                <Fragment key={index}>{withCitations(line)}<br /></Fragment>
              ))}
            </div>
          ) : running ? (
            <p>Searching the brain…</p>
          ) : null}
          {error && <p className="ask-error" role="alert">{error}</p>}
        </section>
      )}
    </>
  );
}
