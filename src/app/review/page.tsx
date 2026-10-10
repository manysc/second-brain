import { AppShell } from "@/Presentation/Components/AppShell";
import { isUncategorized } from "@/Domain";
import { useCases } from "@/composition";
import { TopicProposalList } from "@/Presentation/Components/TopicProposalList";
import { ReviewCandidateList } from "@/Presentation/Components/ReviewCandidateList";
export default async function Review({ searchParams }: { searchParams: Promise<{ error?: string }> }) { const [reviewCandidates, proposals, topics] = await Promise.all([useCases.listPendingReview(), useCases.listTopicProposals(), useCases.listTopics()]); const error = (await searchParams).error; const topicOptions = topics.filter((topic) => !isUncategorized(topic)).map(({ id, name }) => ({ id, name })); return <AppShell><div className="page-head"><div><p className="eyebrow">Human review</p><h1>Keep the AI honest</h1><p className="lede">Suggestions remain suggestions until you confirm them. Inspect the evidence before promoting anything.</p></div></div>{error ? <p className="error-banner">{error}</p> : null}<TopicProposalList proposals={proposals} topics={topicOptions} /><ReviewCandidateList candidates={reviewCandidates} topics={topicOptions} /></AppShell>; }
