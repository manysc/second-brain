import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { searchItems } from "@/lib/api";
import type { KnowledgeItem } from "@/lib/domain";

const PROMPTS = [
  "What should I follow up on?",
  "What changed about Shift Plan?",
  "What unanswered questions keep recurring?",
];

// Mirrors the topics/[id] detail page's ideas/questions/decisions/actions column layout.
function ItemColumns({ items }: { items: KnowledgeItem[] }) {
  const ideas = items.filter((i) => i.type === "IDEA");
  const questions = items.filter((i) => i.type === "QUESTION");
  const decisions = items.filter((i) => i.type === "DECISION");
  const actions = items.filter((i) => i.type === "ACTION");

  return (
    <div className="topic-columns">
      <section>
        <div className="section-heading"><div><p className="eyebrow">Emerging thinking</p><h2>Ideas</h2></div></div>
        {ideas.length ? ideas.map((i) => <div key={i.id}><KnowledgeCard item={i} /></div>) : <p className="empty">No matching ideas.</p>}
      </section>
      <section>
        <div className="section-heading"><div><p className="eyebrow">Open edges</p><h2>Questions</h2></div></div>
        {questions.length ? questions.map((i) => <div key={i.id}><KnowledgeCard item={i} /></div>) : <p className="empty">No matching questions.</p>}
      </section>
      <section>
        <div className="section-heading"><div><p className="eyebrow">Direction set</p><h2>Decisions</h2></div></div>
        {decisions.length ? decisions.map((i) => <div key={i.id}><KnowledgeCard item={i} /></div>) : <p className="empty">No matching decisions.</p>}
      </section>
      <section>
        <div className="section-heading"><div><p className="eyebrow">Work in motion</p><h2>Actions</h2></div></div>
        {actions.length ? actions.map((i) => <div key={i.id}><KnowledgeCard item={i} /></div>) : <p className="empty">No matching actions.</p>}
      </section>
    </div>
  );
}

export default async function Ask({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const query = ((await searchParams).q ?? "").trim();
  const { items, topics } = query ? await searchItems(query) : { items: [], topics: [] };
  // avoid showing the same item twice: once under its topic, once again in the flat list below
  const topicItemIds = new Set(topics.flatMap((topic) => topic.items.map((item) => item.id)));
  const itemsWithoutTopic = items.filter((item) => !topicItemIds.has(item.id));

  return (
    <AppShell>
      <div className="ask-page">
        <p className="eyebrow">Ask my brain / Local retrieval</p>
        <h1>What do you need to know?</h1>
        <p className="lede">Search across meetings, topics, relationships and evidence for the closest matching facts.</p>
        <form className="ask-box" action="/ask">
          <textarea name="q" defaultValue={query} placeholder="What should I follow up on?" aria-label="Question" />
          <button type="submit">Ask <span>↗</span></button>
        </form>
        <div className="prompt-row">
          {PROMPTS.map((prompt) => (
            <a key={prompt} href={`/ask?q=${encodeURIComponent(prompt)}`}>{prompt}</a>
          ))}
        </div>
        {query && (
          <section className="answer">
            <p className="eyebrow">Results / evidence-backed</p>
            <h2>{query}</h2>
            {topics.length > 0 && (
              <div className="topic-results">
                {topics.map((topic) => (
                  <div key={topic.id} className="topic-result">
                    <h3><Link href={`/topics/${topic.id}`}>{topic.name}</Link> <span>({topic.items.length})</span></h3>
                    <ItemColumns items={topic.items} />
                  </div>
                ))}
              </div>
            )}
            <p className="eyebrow">Matching items</p>
            {itemsWithoutTopic.length ? <ItemColumns items={itemsWithoutTopic} /> : <p>No additional matching items found.</p>}
          </section>
        )}
      </div>
    </AppShell>
  );
}
