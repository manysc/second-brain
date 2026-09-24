import { startup } from "@anthropic-ai/claude-agent-sdk";
import type { ModelInfo, SDKUserMessage } from "@anthropic-ai/claude-agent-sdk";

const INIT_TIMEOUT_MS = 60_000;
const CACHE_TTL_MS = 10 * 60_000;

type ModelCache = { cached: { models: ModelInfo[]; at: number } | null; inflight: Promise<ModelInfo[]> | null };

// Kept on globalThis so `next dev` HMR module reloads don't drop the cache or the in-flight lookup.
const globalStore = globalThis as typeof globalThis & { __availableModels?: ModelCache };
const state: ModelCache = (globalStore.__availableModels ??= { cached: null, inflight: null });

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

// Spawning the CLI to list models is slow (seconds), so share one lookup between callers and cache successes.
export function getAvailableModels(): Promise<ModelInfo[]> {
  if (state.cached && Date.now() - state.cached.at < CACHE_TTL_MS) return Promise.resolve(state.cached.models);
  state.inflight ??= fetchLiveModels()
    .then((models) => {
      state.cached = { models, at: Date.now() };
      return models;
    })
    .finally(() => {
      state.inflight = null;
    });
  return state.inflight;
}
