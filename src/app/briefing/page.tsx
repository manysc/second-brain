import { AppShell } from "@/components/AppShell";
import { FollowUpTopicCard } from "@/components/FollowUpTopicCard";
import { getFollowUp } from "@/lib/api";

export default async function Briefing() {
  const followUp = await getFollowUp();
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

