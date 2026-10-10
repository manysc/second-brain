// HTTP handler behind src/app/api/topics/[id]/images/[imageId].
import { useCases } from "@/composition";

/** GET /api/topics/[id]/images/[imageId]: the storage bucket is private, so browsers load images through the app. */
export async function getTopicImage(
  _request: Request,
  { params }: { params: Promise<{ id: string; imageId: string }> },
): Promise<Response> {
  const { id, imageId } = await params;
  const image = await useCases.loadTopicImage(id, imageId);
  if (image.kind === "unreachable") return new Response("Image service unavailable", { status: 502 });
  if (image.kind !== "ok") return new Response("Image not found", { status: image.kind === "missing" ? 404 : 502 });

  return new Response(image.body, {
    headers: {
      "Content-Type": image.contentType ?? "application/octet-stream",
      // image ids are never reused, so the bytes behind a URL never change
      "Cache-Control": "private, max-age=3600",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
