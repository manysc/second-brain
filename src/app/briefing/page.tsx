import { stakeholderOptions } from "@/Domain";
import { AppShell } from "@/Presentation/Components/AppShell";
import { BriefingFilterBar } from "@/Presentation/Components/BriefingFilterBar";
import { FollowUpTopicCard } from "@/Presentation/Components/FollowUpTopicCard";
import { StaleItemsNote } from "@/Presentation/Components/StaleItemsNote";
import { briefingHref, isNarrowed, parseBriefingFilters, toFollowUpQuery } from "@/Presentation/briefingFilters";
import { useCases } from "@/composition";

export default async function Briefing({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const filters = parseBriefingFilters(await searchParams);
  const [followUp, topics, meetings] = await Promise.all([
    useCases.getFollowUp(toFollowUpQuery(filters)),
    useCases.listTopics(),
    useCases.listMeetings(),
  ]);
  const nothingToShow = isNarrowed(filters)
    ? "No follow-up items match these filters."
    : followUp.hiddenStaleCount
      ? "Nothing recent needs follow-up."
      : "Nothing needs follow-up right now.";

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
      <BriefingFilterBar
        filters={filters}
        stakeholders={stakeholderOptions(topics)}
        meetings={meetings.map(({ id, title, date }) => ({ id, title, date }))}
        topics={topics.map(({ id, name }) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name))}
      />
      <StaleItemsNote
        count={followUp.hiddenStaleCount}
        days={followUp.maxAgeDays}
        showAllHref={briefingHref({ ...filters, showStale: true })}
      />
      {followUp.totalTopics > followUp.topics.length ? (
        <p className="briefing-note">
          Showing {followUp.topics.length} of {followUp.totalTopics} topics.
        </p>
      ) : null}
      {followUp.topics.length ? (
        <div className="briefing-grid">
          {followUp.topics.map((topic) => (
            <FollowUpTopicCard key={topic.topic.id} topic={topic} />
          ))}
        </div>
      ) : (
        <p className="empty">{nothingToShow}</p>
      )}
    </AppShell>
  );
}
