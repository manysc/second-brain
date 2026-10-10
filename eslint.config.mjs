import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// The dependency rule from architecture.md: Domain <- Application <- Infrastructure / Presentation, wired together
// only in src/composition.ts. Each entry lists what a layer must NOT import; tests/frontend/architecture.test.ts
// checks that these rules really fire.
const layer = (name) => ({ group: [`@/${name}`, `@/${name}/**`, `**/${name}/**`], message: `${name} is an outer layer here.` });
const composition = { group: ["@/composition", "**/composition"], message: "Only pages, route handlers and controllers use the composition root." };
const routing = { group: ["@/app/**", "**/app/**"], message: "src/app is the routing shell; nothing depends on it." };
const frameworks = {
  group: ["next", "next/**", "react", "react/**", "react-dom", "react-dom/**", "node:*", "@anthropic-ai/**"],
  message: "Domain and Application are plain TypeScript: no framework, runtime or SDK imports.",
};
const boundaries = (files, patterns) => ({ files, rules: { "no-restricted-imports": ["error", { patterns }] } });

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  boundaries(["src/Domain/**"], [layer("Application"), layer("Infrastructure"), layer("Presentation"), composition, routing, frameworks]),
  boundaries(["src/Application/**"], [layer("Infrastructure"), layer("Presentation"), composition, routing, frameworks]),
  boundaries(["src/Infrastructure/**"], [layer("Presentation"), composition, routing]),
  // controllers reach infrastructure only through the use cases the composition root hands them
  boundaries(["src/Presentation/**", "src/app/**"], [layer("Infrastructure")]),
  // components may run in the browser: no adapters, and no composition root (it pulls in Node-only code)
  boundaries(["src/Presentation/Components/**"], [layer("Infrastructure"), composition, routing]),
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // not app code: the Python virtualenv ships vendored JS, and Playwright writes traces/reports
    "backend/**",
    "test-results/**",
    "playwright-report/**",
  ]),
]);

export default eslintConfig;
