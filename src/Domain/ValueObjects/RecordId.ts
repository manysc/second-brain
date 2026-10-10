export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type RecordRef = { kind: "topic"; topicId: string } | { kind: "item"; meetingId: string };

/** Record ids are UUIDs for topics and "<meetingId>:<key>" for items; anything else is not a known record. */
export function classifyRecordId(id: string): RecordRef | null {
  if (UUID.test(id)) return { kind: "topic", topicId: id };
  const meetingId = id.includes(":") ? id.split(":", 1)[0] : null;
  return meetingId ? { kind: "item", meetingId } : null;
}
