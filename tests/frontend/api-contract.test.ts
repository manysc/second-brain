// @vitest-environment node
// Every request the frontend makes must exist in the backend's OpenAPI snapshot
// (backend/tests/fixtures/openapi.snapshot.json, kept current by backend/tests/test_contracts.py),
// so the Next.js app and the FastAPI backend cannot drift apart silently.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { CASES } from "./support/apiCases";

type OpenApi = { paths: Record<string, Record<string, unknown>> };

const openapi: OpenApi = JSON.parse(
  readFileSync(path.join(process.cwd(), "backend", "tests", "fixtures", "openapi.snapshot.json"), "utf-8"),
);

const routes = Object.entries(openapi.paths).map(([template, operations]) => ({
  template,
  pattern: new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`),
  methods: new Set(Object.keys(operations).map((m) => m.toUpperCase())),
}));

function operationFor(method: string, pathWithQuery: string) {
  const pathname = pathWithQuery.split("?")[0];
  // FastAPI resolves routes in declaration order, but a concrete path matching several templates is fine as long
  // as one of them serves the method (e.g. /api/topics/suggested-merges vs /api/topics/{topic_id})
  return routes.find((route) => route.pattern.test(pathname) && route.methods.has(method));
}

const requests = [
  ...CASES.map(({ name, method, path: p }) => ({ name, method, path: p })),
  { name: "addTopicImage", method: "POST", path: "/api/topics/t1/images" },
  { name: "loadTopicImage", method: "GET", path: "/api/topics/t1/images/img" },
];

describe("frontend/backend contract", () => {
  it.each(requests)("$name ($method $path) is served by the backend", ({ method, path: p }) => {
    expect(operationFor(method, p), `${method} ${p} is not in the OpenAPI snapshot`).toBeDefined();
  });

  it("detects a request the backend does not serve", () => {
    expect(operationFor("PUT", "/api/topics/t1")).toBeUndefined();
    expect(operationFor("GET", "/api/nope")).toBeUndefined();
  });
});
