import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { getMeetings } from "@/lib/api";

function dateParts(date: string) {
  const parsed = new Date(`${date}T00:00:00`);
  return {
    day: parsed.getDate().toString().padStart(2, "0"),
    month: parsed.toLocaleString("en-US", { month: "short" }).toUpperCase(),
    year: parsed.getFullYear(),
  };
}

export default async function Meetings() {
  const meetings = await getMeetings();
  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Meetings</p>
          <h1>Meeting archive</h1>
          <p className="lede">Every extracted signal, held close to its source.</p>
        </div>
      </div>
      {meetings.map((meeting) => {
        const { day, month, year } = dateParts(meeting.date);
        const count = (type: string) => meeting.items.filter((item) => item.type === type).length;
        return (
          <section className="meeting-row" key={meeting.id}>
            <div className="date-block">
              <strong>{day}</strong>
              <span>
                {month}
                <br />
                {year}
              </span>
            </div>
            <div className="meeting-main">
              <p className="eyebrow">{meeting.id}</p>
              <h2>{meeting.title}</h2>
              <p>One-on-one conversation with persistent threads across planning, releases, integration and performance.</p>
              <div className="count-row">
                <span>{count("IDEA")} ideas</span>
                <span>{count("DECISION")} decisions</span>
                <span>{count("ACTION")} actions</span>
                <span>{count("QUESTION")} questions</span>
                <span>{meeting.reviewCandidates.length} review candidates</span>
              </div>
            </div>
            <Link className="arrow-link" href={`/meetings/${meeting.id}`}>
              Open meeting <span>↗</span>
            </Link>
          </section>
        );
      })}
    </AppShell>
  );
}

