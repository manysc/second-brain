// What the Briefing page reads from and writes to its URL. Pure, so the server page and the filter bar (a client
// component) share it and it is unit-tested directly.
import { DEFAULT_FOLLOW_UP_TOPICS, type FollowUpQuery } from "@/Domain";

export const BRIEFING_TOPIC_LIMITS = [DEFAULT_FOLLOW_UP_TOPICS, 10, 20, 50] as const;

export type BriefingFilters = {
  /** false (the default) hides items with no recent activity */
  showStale: boolean;
  /** how many topics to show; one of BRIEFING_TOPIC_LIMITS */
  limit: number;
  stakeholders: string[];
  meetingIds: string[];
  topicIds: string[];
};

export const DEFAULT_BRIEFING_FILTERS: BriefingFilters = {
  showStale: false,
  limit: DEFAULT_FOLLOW_UP_TOPICS,
  stakeholders: [],
  meetingIds: [],
  topicIds: [],
};

type SearchParams = Record<string, string | string[] | undefined>;

// a query key may be missing, given once or repeated
function values(raw: string | string[] | undefined): string[] {
  const list = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
  return [...new Set(list.map((value) => value.trim()).filter(Boolean))];
}

/** Reads ?stakeholder=&meeting=&topic= (each repeatable), ?stale=show and ?limit=; anything else is the default. */
export function parseBriefingFilters(params: SearchParams): BriefingFilters {
  const limit = Number(values(params.limit)[0]);
  return {
    showStale: values(params.stale).includes("show"),
    limit: BRIEFING_TOPIC_LIMITS.find((allowed) => allowed === limit) ?? DEFAULT_FOLLOW_UP_TOPICS,
    stakeholders: values(params.stakeholder),
    meetingIds: values(params.meeting),
    topicIds: values(params.topic),
  };
}

/** The Briefing URL for these filters; defaults are left out, so no filters is plain /briefing. */
export function briefingHref(filters: BriefingFilters): string {
  const params = new URLSearchParams();
  for (const name of filters.stakeholders) params.append("stakeholder", name);
  for (const meetingId of filters.meetingIds) params.append("meeting", meetingId);
  for (const topicId of filters.topicIds) params.append("topic", topicId);
  if (filters.showStale) params.set("stale", "show");
  if (filters.limit !== DEFAULT_FOLLOW_UP_TOPICS) params.set("limit", String(filters.limit));
  const query = params.toString();
  return query ? `/briefing?${query}` : "/briefing";
}

/** Whether the briefing is narrowed to some people, meetings or topics. */
export function isNarrowed(filters: BriefingFilters): boolean {
  return filters.stakeholders.length + filters.meetingIds.length + filters.topicIds.length > 0;
}

/** Hiding stale items is the backend's default, so the cut-off is only named when it is switched off. */
export function toFollowUpQuery(filters: BriefingFilters): FollowUpQuery {
  return {
    limit: filters.limit,
    maxAgeDays: filters.showStale ? 0 : undefined,
    stakeholders: filters.stakeholders,
    meetingIds: filters.meetingIds,
    topicIds: filters.topicIds,
  };
}
