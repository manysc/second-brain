#!/usr/bin/env node
// Cross-platform launcher for the Brain Assistant MCP server (Python, backend/mcp_server).
//
//   node scripts/mcp-server.mjs            start the stdio server (what .mcp.json runs)
//   node scripts/mcp-server.mjs --check    verify the environment and that the server builds
//   node scripts/mcp-server.mjs --test     run the MCP test suite
//
// Resolves paths from this file's location, never the working directory. stdout is reserved for
// MCP JSON-RPC while serving, so every diagnostic here goes to stderr.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "backend");
const venvPython =
  process.platform === "win32"
    ? path.join(backend, ".venv", "Scripts", "python.exe")
    : path.join(backend, ".venv", "bin", "python");
const python = process.env.BRAIN_MCP_PYTHON || venvPython;

if (!existsSync(python)) {
  console.error(
    `brain-assistant MCP: Python interpreter not found at ${python}.\n` +
      "Create it with: cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt\n" +
      "(use .venv/bin/python on macOS/Linux), or set BRAIN_MCP_PYTHON.",
  );
  process.exit(2);
}

const mode = process.argv[2];
let args;
if (mode === "--check") {
  args = [
    "-c",
    "import mcp_server.server as s; s.create_server(); print('brain-assistant MCP: build check passed')",
  ];
} else if (mode === "--test") {
  args = ["-m", "pytest", "tests/mcp_tests", "-q", ...process.argv.slice(3)];
} else {
  args = ["-m", "mcp_server"];
}

const child = spawn(python, args, {
  cwd: backend,
  stdio: "inherit",
  env: { ...process.env, PYTHONPATH: backend, PYTHONUNBUFFERED: "1" },
});
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
child.on("error", (error) => {
  console.error(`brain-assistant MCP: failed to start (${error.code ?? "error"})`);
  process.exit(2);
});
