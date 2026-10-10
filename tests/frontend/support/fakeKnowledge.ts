import { vi, type Mock } from "vitest";
import type { KnowledgeRepository } from "@/Application/Interfaces/KnowledgeRepository";

export type FakeKnowledgeRepository = KnowledgeRepository & { [K in keyof KnowledgeRepository]: Mock };

/** What a method answers: a value to resolve to, an Error to reject with, or a function of the call's arguments. */
export type Answers = Partial<Record<keyof KnowledgeRepository, unknown>>;

/**
 * An in-memory stand-in for the knowledge base port. Every method is a spy that resolves to `{}` unless an
 * answer is given for it, so a use-case test states only the calls it cares about.
 */
export function fakeKnowledge(answers: Answers = {}): FakeKnowledgeRepository {
  const spies = new Map<string, Mock>();
  return new Proxy({} as FakeKnowledgeRepository, {
    get(_target, name: string) {
      if (!spies.has(name)) {
        const answer = (answers as Record<string, unknown>)[name];
        spies.set(
          name,
          vi.fn(async (...args: unknown[]) => {
            if (answer instanceof Error) throw answer;
            return typeof answer === "function" ? answer(...args) : (answer ?? {});
          }),
        );
      }
      return spies.get(name);
    },
  });
}
