import type {
  FollowUpResponse,
  GraphData,
  KnowledgeItem,
  Meeting,
  ReviewCandidate,
  ReviewDecision,
  SearchResult,
  TopicProposal,
} from "@/Domain";
import type { IngestResult } from "../DTOs/Knowledge";
import type { KnowledgeRepository } from "../Interfaces/KnowledgeRepository";

/** Meetings, human review and the whole-knowledge-base views. */
export function knowledgeUseCases(knowledge: KnowledgeRepository) {
  return {
    listMeetings: (): Promise<Meeting[]> => knowledge.getMeetings(),

    getMeeting: (meetingId: string): Promise<Meeting> => knowledge.getMeetingById(meetingId),

    getLatestMeeting: (): Promise<Meeting> => knowledge.getMeeting(),

    /** The same ingestion the backend runs on startup: pulls every extract from storage into the knowledge base. */
    ingestMeetings: (): Promise<IngestResult> => knowledge.ingestMeetings(),

    listPendingReview: (): Promise<ReviewCandidate[]> => knowledge.getReview(),

    /** The topic only matters when accepting: "" files under Uncategorized, undefined lets the backend match. */
    decideReviewCandidate: (candidateId: string, decision: ReviewDecision, topicId?: string): Promise<ReviewCandidate> =>
      knowledge.updateReviewStatus(candidateId, decision, decision === "ACCEPTED" ? topicId : undefined),

    listTopicProposals: (): Promise<TopicProposal[]> => knowledge.getTopicProposals(),

    /** existingTopicId wins over topicName; topicName null = the suggested name. */
    acceptTopicProposal: (
      suggestedName: string,
      topicName: string | null,
      existingTopicId: string | null,
    ): Promise<KnowledgeItem[]> => knowledge.acceptTopicProposal(suggestedName, topicName, existingTopicId),

    rejectTopicProposal: (suggestedName: string): Promise<void> => knowledge.rejectTopicProposal(suggestedName),

    getGraph: (minSimilarity?: number): Promise<GraphData> => knowledge.getGraph(minSimilarity),

    getFollowUp: (limit?: number, dueSoonDays?: number): Promise<FollowUpResponse> =>
      knowledge.getFollowUp(limit, dueSoonDays),

    search: (query: string): Promise<SearchResult> => knowledge.searchItems(query),
  };
}
