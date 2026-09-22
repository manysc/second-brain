import { startup } from "@anthropic-ai/claude-agent-sdk";
import type { ModelInfo, SDKUserMessage } from "@anthropic-ai/claude-agent-sdk";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INIT_TIMEOUT_MS = 10_000;

async function* noInput(): AsyncGenerator<SDKUserMessage> {
  await new Promise<never>(() => {}); // never yields — no turn is ever sent
}

async function fetchLiveModels(): Promise<ModelInfo[]> {
  const warm = await startup({
    options: { cwd: process.cwd(), settingSources: [] },
    initializeTimeoutMs: INIT_TIMEOUT_MS,
  });
  const run = warm.query(noInput());
  try {
    return await run.supportedModels();
  } finally {
    run.close(); // NOT warm.close() — it's a no-op once .query() has been called
  }
}

export async function GET() {
  try {
    return Response.json({ models: await fetchLiveModels() });
  } catch (error) {
    console.error("supportedModels() failed:", error);
    return Response.json({ models: [] });
  }
}
