"use client";

import { useState, useTransition } from "react";
import { ingestMeetingsAction } from "@/lib/actions";
import type { IngestResult } from "@/lib/api";

function describe({ meetings, new: added, updated }: IngestResult): string {
  const checked = `${meetings} checked`;
  if (added === 0 && updated === 0) return `No new or changed meetings · ${checked}`;
  const parts: string[] = [];
  if (added) parts.push(`${added} new meeting${added === 1 ? "" : "s"}`);
  if (updated) parts.push(`${updated} updated`);
  return `${parts.join(", ")} · ${checked}`;
}

export function IngestMeetingsButton() {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  function ingest() {
    setError(null);
    setStatus(null);
    startTransition(async () => {
      const result = await ingestMeetingsAction();
      if (result.error) setError(result.error);
      else if (result.result) setStatus(describe(result.result));
    });
  }

  return (
    <div className="ingest-control">
      <button type="button" onClick={ingest} disabled={pending}>
        {pending ? "Ingesting…" : "Ingest from SeaweedFS"}
      </button>
      {error ? <p className="error-banner">{error}</p> : null}
      {status ? <p className="ingest-status">{status}</p> : null}
    </div>
  );
}
