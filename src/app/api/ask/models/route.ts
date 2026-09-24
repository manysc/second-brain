import { getAvailableModels } from "@/lib/available-models";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return Response.json({ models: await getAvailableModels() });
  } catch (error) {
    console.error("supportedModels() failed:", error);
    return Response.json({ models: [], error: "Model list unavailable." }, { status: 503 });
  }
}
