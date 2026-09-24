import { AppShell } from "@/components/AppShell";
import { AskConversation } from "@/components/AskConversation";
import { getAvailableModels } from "@/lib/available-models";

const PROMPTS = [
  "What should I follow up on?",
  "What changed about Shift Plan?",
  "What unanswered questions keep recurring?",
  "Which open actions are highest priority, and who owns them?",
  "Why was the most recent decision made? Show the evidence.",
];

export default async function Ask({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; model?: string; effort?: string }>;
}) {
  void getAvailableModels().catch(() => {}); // start the slow lookup now; the client fetch shares it
  const params = await searchParams;
  const query = (params.q ?? "").trim();
  const model = (params.model ?? "").trim() || undefined;
  const effort = (params.effort ?? "").trim() || undefined;

  return (
    <AppShell>
      <div className="ask-page">
        <p className="eyebrow">Ask my brain / Brain Assistant</p>
        <h1>What do you need to know?</h1>
        <p className="lede">Answers use the same read-only Brain Assistant tools as Claude Code, with record IDs cited for every claim.</p>
        <AskConversation
          key={query}
          initialQuery={query}
          prompts={PROMPTS}
          initialModel={model}
          initialEffort={effort}
        />
      </div>
    </AppShell>
  );
}
