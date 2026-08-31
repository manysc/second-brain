import { AppShell } from "@/components/AppShell";
import { TopicGrid } from "@/components/TopicGrid";
import { getTopics } from "@/lib/api";
import { createTopicAction } from "@/lib/actions";

export default async function Topics({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const topics = await getTopics();
  const error = (await searchParams).error;

  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Topics</p>
          <h1>Persistent threads</h1>
          <p className="lede">A topic is a living body of knowledge, not a label. Start with what the meeting made visible.</p>
        </div>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      <form className="topic-toolbar" action={createTopicAction}>
        <input name="name" placeholder="New topic name" required />
        <button>Create topic</button>
      </form>
      <TopicGrid topics={topics} />
    </AppShell>
  );
}


