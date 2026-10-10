// @vitest-environment node
// The layer boundaries are enforced by ESLint (eslint.config.mjs). This checks the enforcement itself: a forbidden
// import must be reported, an allowed one must not, so a broken rule cannot pass silently.
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: process.cwd() });

async function violations(filePath: string, code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.filter((message) => message.ruleId === "no-restricted-imports").map((message) => message.message);
}

const FORBIDDEN: [string, string][] = [
  ["src/Domain/Entities/Topic.ts", 'import type { NewItem } from "@/Application/DTOs/Knowledge";'],
  ["src/Domain/Entities/Topic.ts", 'import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";'],
  ["src/Domain/Entities/Topic.ts", 'import { TagChip } from "@/Presentation/Components/TagChip";'],
  ["src/Domain/Entities/Topic.ts", 'import { useState } from "react";'],
  ["src/Domain/ValueObjects/Tag.ts", 'import path from "node:path";'],
  ["src/Application/UseCases/topics.ts", 'import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";'],
  ["src/Application/UseCases/topics.ts", 'import { BackendApiClient } from "../../Infrastructure/ExternalServices/BackendApiClient";'],
  ["src/Application/UseCases/topics.ts", 'import { revalidatePath } from "next/cache";'],
  ["src/Application/UseCases/ask.ts", 'import { query } from "@anthropic-ai/claude-agent-sdk";'],
  ["src/Application/UseCases/topics.ts", 'import { useCases } from "@/composition";'],
  ["src/Infrastructure/ExternalServices/BackendApiClient.ts", 'import { field } from "@/Presentation/Controllers/support";'],
  ["src/Infrastructure/ExternalServices/BackendApiClient.ts", 'import { useCases } from "@/composition";'],
  ["src/Presentation/Controllers/topicActions.ts", 'import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";'],
  ["src/Presentation/Components/TagChip.tsx", 'import { FsAskSessionStore } from "@/Infrastructure/Persistence/FsAskSessionStore";'],
  ["src/Presentation/Components/TagChip.tsx", 'import { useCases } from "@/composition";'],
  ["src/app/topics/page.tsx", 'import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";'],
];

const ALLOWED: [string, string][] = [
  ["src/Domain/Entities/Topic.ts", 'import { PRIORITY_RANK } from "../ValueObjects/Priority";'],
  ["src/Application/UseCases/topics.ts", 'import type { Topic } from "@/Domain";'],
  ["src/Application/UseCases/topics.ts", 'import { ValidationError } from "../Errors";'],
  ["src/Infrastructure/ExternalServices/BackendApiClient.ts", 'import type { KnowledgeRepository } from "@/Application/Interfaces/KnowledgeRepository";'],
  ["src/Infrastructure/Persistence/FsAskSessionStore.ts", 'import path from "node:path";'],
  ["src/Presentation/Controllers/topicActions.ts", 'import { useCases } from "@/composition";'],
  ["src/Presentation/Components/TagChip.tsx", 'import type { AskEvent } from "@/Application/DTOs/Ask";'],
  ["src/Presentation/Components/TagChip.tsx", 'import { useState } from "react";'],
  ["src/app/topics/page.tsx", 'import { useCases } from "@/composition";'],
  ["src/composition.ts", 'import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";'],
];

describe("layer boundaries (eslint)", () => {
  // the first lint loads the whole Next/TypeScript ESLint config, which takes far longer than a test's default budget
  beforeAll(async () => {
    await eslint.lintText("export {};", { filePath: "src/Domain/index.ts" });
  }, 180_000);

  it.each(FORBIDDEN)("%s may not: %s", async (filePath, code) => {
    expect(await violations(filePath, code)).toHaveLength(1);
  });

  it.each(ALLOWED)("%s may: %s", async (filePath, code) => {
    expect(await violations(filePath, code)).toEqual([]);
  });
});
