import { AppShell } from "@/components/AppShell";
import { AskConversation } from "@/components/AskConversation";

const PROMPTS = [
  "What should I follow up on?",
  "What changed about Shift Plan?",
  "What unanswered questions keep recurring?",
  "Which open actions are highest priority, and who owns them?",
  "Why was the most recent decision made? Show the evidence.",
];

export default async function Ask({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const query = ((await searchParams).q ?? "").trim();

  return (
    <AppShell>
      <div className="ask-page">
        <p className="eyebrow">Ask my brain / Brain Assistant</p>
        <h1>What do you need to know?</h1>
        <p className="lede">Answers use the same read-only Brain Assistant tools as Claude Code, with record IDs cited for every claim.</p>
        <AskConversation key={query} initialQuery={query} prompts={PROMPTS} />
      </div>
    </AppShell>
  );
}
