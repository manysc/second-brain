import { fetchTopicImage } from "@/lib/api";

// The SeaweedFS bucket is private, so the browser loads topic images through the app instead.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string; imageId: string }> }) {
  const { id, imageId } = await params;
  const upstream = await fetchTopicImage(id, imageId).catch(() => null);
  if (!upstream) return new Response("Image service unavailable", { status: 502 });
  if (!upstream.ok) return new Response("Image not found", { status: upstream.status === 404 ? 404 : 502 });

  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
      // image ids are never reused, so the bytes behind a URL never change
      "Cache-Control": "private, max-age=3600",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
