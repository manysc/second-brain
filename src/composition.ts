// Composition root: the one module that knows every layer. It builds the infrastructure adapters and hands them
// to the application's use cases. Server-side only (the adapters use Node APIs and server environment variables):
// pages, route handlers and server actions import `useCases` from here; client components never do.
import { askUseCases } from "@/Application/UseCases/ask";
import { itemUseCases } from "@/Application/UseCases/items";
import { knowledgeUseCases } from "@/Application/UseCases/knowledge";
import { topicUseCases } from "@/Application/UseCases/topics";
import { BackendApiClient } from "@/Infrastructure/ExternalServices/BackendApiClient";
import { ClaudeAgentSdkAsk } from "@/Infrastructure/ExternalServices/ClaudeAgentSdkAsk";
import { ClaudeModelCatalog } from "@/Infrastructure/ExternalServices/ClaudeModelCatalog";
import { FsAskSessionStore } from "@/Infrastructure/Persistence/FsAskSessionStore";

const knowledge = new BackendApiClient();

export const useCases = {
  ...knowledgeUseCases(knowledge),
  ...itemUseCases(knowledge),
  ...topicUseCases(knowledge),
  ...askUseCases(new ClaudeAgentSdkAsk(), new FsAskSessionStore(), new ClaudeModelCatalog()),
};

export type UseCases = typeof useCases;
