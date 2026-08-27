import fs from "node:fs";
import path from "node:path";

const file = path.join(process.cwd(), "data", "meeting-extract.json");
const source = fs.readFileSync(file, "utf8").trim();
const data = JSON.parse(source.startsWith("{") ? source : `{${source}}`);
const expected = { ideas: 2, decisions: 5, actions: 10, questions: 7, review_candidates: 4 };
for (const [key, count] of Object.entries(expected)) {
  if (data[key].length !== count) throw new Error(`${key}: expected ${count}, got ${data[key].length}`);
}
const all = [...data.ideas, ...data.decisions, ...data.actions, ...data.questions];
const find = (id) => all.find((item) => item.candidate_id === id);
for (const [sourceId, targetId] of [["A-007", "I-002"], ["D-001", "A-002"], ["D-001", "Q-001"], ["D-004", "A-001"], ["D-004", "A-009"], ["D-004", "A-010"]]) {
  if (!find(sourceId).related_candidate_ids.includes(targetId)) throw new Error(`${sourceId} -> ${targetId} missing`);
}
if (find("A-009").due_date !== "2026-08-25") throw new Error("A-009 date was not preserved");
if (find("A-010").due_date !== null) throw new Error("A-010 ambiguous date was fabricated");
if (data.review_candidates.length !== 4) throw new Error("Review candidates were promoted or lost");
console.log(`Verified ${data.meeting.meeting_id}: 2 ideas, 5 decisions, 10 actions, 7 questions, 4 review candidates; relationships and date ambiguity preserved.`);
