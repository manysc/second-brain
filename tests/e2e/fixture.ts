import { execFileSync } from "node:child_process";
import path from "node:path";
import type { Page } from "@playwright/test";

export type Seed = {
  run: string;
  meetingId: string;
  topicId: string;
  topicName: string;
  targetTopicId: string;
  targetTopicName: string;
  itemId: string;
  itemDescription: string;
  acceptDescription: string;
  rejectDescription: string;
};

const BACKEND_DIR = path.join(process.cwd(), "backend");
const PYTHON = path.join(BACKEND_DIR, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

function fixture(command: "seed" | "cleanup", run: string): string {
  return execFileSync(PYTHON, ["-m", "tests.e2e_fixture", command, run], {
    cwd: BACKEND_DIR,
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 120_000,
  });
}

export function seed(run: string): Seed {
  const output = fixture("seed", run).trim().split("\n");
  return JSON.parse(output[output.length - 1]) as Seed;
}

export function cleanup(run: string): void {
  fixture("cleanup", run);
}

/** The seeded dataset, published by global-setup through the environment workers inherit. */
export function seeded(): Seed {
  const raw = process.env.E2E_SEED;
  if (!raw) throw new Error("E2E_SEED is not set; run the suite through `npm run test:e2e`");
  return JSON.parse(raw) as Seed;
}

/** Navigates and waits until client components have hydrated (next dev compiles on demand, so a click can otherwise
 * land on server-rendered HTML whose handlers are not attached yet). */
export async function gotoHydrated(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}
