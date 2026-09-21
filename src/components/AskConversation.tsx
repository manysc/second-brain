"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useState, type FormEvent, type ReactNode } from "react";

type ToolCall = { name: string; input: unknown };
type AskEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "done" }
  | { type: "error"; message: string };

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

export function AskConversation({ initialQuery, prompts }: { initialQuery: string; prompts: string[] }) {
  const router = useRouter();
  const [draft, setDraft] = useState(initialQuery);
  const [answer, setAnswer] = useState("");
  const [tools, setTools] = useState<ToolCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(Boolean(initialQuery));

  useEffect(() => {
    if (!initialQuery) return;
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: initialQuery }),
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
            else if (event.type === "error") setError(event.message);
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
  }, [initialQuery]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = draft.trim();
    if (q) router.push(`/ask?q=${encodeURIComponent(q)}`);
  }

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
      <div className="prompt-row">
        {prompts.map((prompt) => (
          <a key={prompt} href={`/ask?q=${encodeURIComponent(prompt)}`}>{prompt}</a>
        ))}
      </div>
      {initialQuery && (
        <section className="answer">
          <p className="eyebrow">Answer / cites record IDs, read-only</p>
          <h2>{initialQuery}</h2>
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
