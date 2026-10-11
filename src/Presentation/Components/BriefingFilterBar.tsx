"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useOptimistic, useTransition } from "react";
import { FOLLOW_UP_MAX_AGE_DAYS } from "@/Domain";
import {
  BRIEFING_TOPIC_LIMITS,
  DEFAULT_BRIEFING_FILTERS,
  briefingHref,
  type BriefingFilters,
} from "@/Presentation/briefingFilters";

type Option = { value: string; label: string };

function toggled(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((current) => current !== value) : [...list, value];
}

function Checklist({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: Option[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  // a value from the URL that is no longer an option (a deleted topic, say) stays listed so it can be unticked
  const listed = [
    ...options,
    ...selected.filter((value) => !options.some((option) => option.value === value)).map((value) => ({ value, label: value })),
  ];
  return (
    <details className="filter-menu">
      <summary className={`filter${selected.length ? " active" : ""}`}>
        {label}
        {selected.length ? ` (${selected.length})` : ""}
      </summary>
      <div className="filter-menu-list" role="group" aria-label={label}>
        {listed.length ? (
          listed.map((option) => (
            <label key={option.value}>
              <input type="checkbox" checked={selected.includes(option.value)} onChange={() => onToggle(option.value)} />
              {option.label}
            </label>
          ))
        ) : (
          <p className="empty">Nothing to choose from yet.</p>
        )}
      </div>
    </details>
  );
}

/** The filters live in the URL: every change navigates, and the page renders the briefing for the new URL. */
export function BriefingFilterBar({
  filters,
  stakeholders,
  meetings,
  topics,
}: {
  filters: BriefingFilters;
  stakeholders: string[];
  meetings: { id: string; title: string; date: string }[];
  topics: { id: string; name: string }[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  // shows the click at once; falls back to the URL's filters when the navigation lands
  const [shown, setShown] = useOptimistic(filters);

  function apply(next: BriefingFilters) {
    startTransition(() => {
      setShown(next);
      router.push(briefingHref(next));
    });
  }

  return (
    <div className="briefing-filters" aria-busy={pending}>
      <Checklist
        label="Stakeholders"
        options={stakeholders.map((name) => ({ value: name, label: name }))}
        selected={shown.stakeholders}
        onToggle={(name) => apply({ ...shown, stakeholders: toggled(shown.stakeholders, name) })}
      />
      <Checklist
        label="Meetings"
        options={meetings.map((meeting) => ({ value: meeting.id, label: `${meeting.date} · ${meeting.title}` }))}
        selected={shown.meetingIds}
        onToggle={(meetingId) => apply({ ...shown, meetingIds: toggled(shown.meetingIds, meetingId) })}
      />
      <Checklist
        label="Topics"
        options={topics.map((topic) => ({ value: topic.id, label: topic.name }))}
        selected={shown.topicIds}
        onToggle={(topicId) => apply({ ...shown, topicIds: toggled(shown.topicIds, topicId) })}
      />
      <label className="graph-toggle">
        <input
          type="checkbox"
          checked={!shown.showStale}
          onChange={(event) => apply({ ...shown, showStale: !event.target.checked })}
        />
        Hide items with no activity in {FOLLOW_UP_MAX_AGE_DAYS} days
      </label>
      <label className="graph-toggle">
        Topics to show
        <select value={shown.limit} onChange={(event) => apply({ ...shown, limit: Number(event.target.value) })}>
          {BRIEFING_TOPIC_LIMITS.map((limit) => (
            <option key={limit} value={limit}>
              {limit}
            </option>
          ))}
        </select>
      </label>
      {briefingHref(shown) === briefingHref(DEFAULT_BRIEFING_FILTERS) ? null : (
        <Link href={briefingHref(DEFAULT_BRIEFING_FILTERS)} className="evidence-link">
          Clear filters
        </Link>
      )}
    </div>
  );
}
