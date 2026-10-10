import path from "node:path";
import { query } from "@anthropic-ai/claude-agent-sdk";
import type { AskEvent } from "@/Application/DTOs/Ask";
import type { AskAgent, AskAgentRequest } from "@/Application/Interfaces/Ask";
import { MCP_SERVER, MCP_TOOL_PREFIX, SESSION_CWD } from "@/Infrastructure/Persistence/FsAskSessionStore";

/** Answers questions with the Claude Agent SDK, restricted to the brain MCP server and nothing else. */
export class ClaudeAgentSdkAsk implements AskAgent {
  async *ask(request: AskAgentRequest): AsyncGenerator<AskEvent> {
    const abort = new AbortController();
    if (request.signal.aborted) abort.abort();
    else request.signal.addEventListener("abort", () => abort.abort());

    const run = query({
      prompt: request.prompt,
      options: {
        abortController: abort,
        cwd: SESSION_CWD,
        ...(request.resumeSessionId ? { resume: request.resumeSessionId } : {}),
        systemPrompt: request.systemPrompt,
        maxTurns: request.maxTurns,
        includePartialMessages: true,
        ...(request.model ? { model: request.model } : {}),
        ...(request.effort ? { effort: request.effort } : {}),
        // Only the allowed brain tools: no built-in tools, no project/user settings, no other MCP servers.
        tools: [],
        allowedTools: request.allowedTools.map((name) => MCP_TOOL_PREFIX + name),
        disallowedTools: request.forbiddenTools.map((name) => MCP_TOOL_PREFIX + name),
        permissionMode: "dontAsk",
        settingSources: [],
        strictMcpConfig: true,
        mcpServers: {
          [MCP_SERVER]: {
            type: "stdio",
            command: "node",
            args: [path.join(process.cwd(), "scripts", "mcp-server.mjs")],
            env: {
              ...(process.env as Record<string, string>),
              BRAIN_ENV: process.env.BRAIN_ENV ?? "development",
              BRAIN_MCP_ALLOW_WRITES: "true",
              BRAIN_MCP_ACTOR: "second-brain-ask",
            },
          },
        },
      },
    });

    for await (const message of run) {
      if (message.type === "system" && message.subtype === "init") {
        yield { type: "meta", model: message.model, effort: message.effort ?? null, sessionId: message.session_id };
      } else if (message.type === "stream_event") {
        const event = message.event;
        if (
          message.parent_tool_use_id === null &&
          event.type === "content_block_delta" &&
          event.delta.type === "text_delta"
        ) {
          yield { type: "text", text: event.delta.text };
        }
      } else if (message.type === "assistant") {
        for (const block of message.message.content) {
          if (block.type === "tool_use") {
            yield { type: "tool", name: block.name.replace(MCP_TOOL_PREFIX, ""), input: block.input };
          }
        }
      } else if (message.type === "result" && message.subtype !== "success") {
        yield { type: "error", message: `Ask ended early (${message.subtype}).` };
      }
    }
  }
}
