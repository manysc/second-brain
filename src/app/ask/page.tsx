import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { searchItems } from "@/lib/api";

const PROMPTS = [
  "What should I follow up on?",
  "What changed about Shift Plan?",
  "What unanswered questions keep recurring?",
];

export default async function Ask({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const query = ((await searchParams).q ?? "").trim();
  const { items, topics } = query ? await searchItems(query) : { items: [], topics: [] };

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
                    <div className="card-grid">
                      {topic.items.map((item) => <KnowledgeCard key={item.id} item={item} />)}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <p className="eyebrow">Matching items</p>
            {items.length ? (
              <div className="card-grid">
                {items.map((item) => <KnowledgeCard key={item.id} item={item} />)}
              </div>
            ) : (
              <p>No matching items found.</p>
            )}
          </section>
        )}
      </div>
    </AppShell>
  );
}
