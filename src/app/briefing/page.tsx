import { AppShell } from "@/Presentation/Components/AppShell";
import { FollowUpTopicCard } from "@/Presentation/Components/FollowUpTopicCard";
import { useCases } from "@/composition";

export default async function Briefing() {
  const followUp = await useCases.getFollowUp();
  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Briefing</p>
          <h1>What to raise in the next meeting</h1>
          <p className="lede">
            Topics ranked by priority, with only the open questions, due actions, and unresolved
            decisions worth carrying forward.
          </p>
        </div>
      </div>
      {followUp.topics.length ? (
        <div className="briefing-grid">
          {followUp.topics.map((topic) => (
            <FollowUpTopicCard key={topic.topic.id} topic={topic} />
          ))}
        </div>
      ) : (
        <p className="empty">Nothing needs follow-up right now.</p>
      )}
    </AppShell>
  );
}

