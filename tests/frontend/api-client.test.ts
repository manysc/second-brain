// @vitest-environment node
// Characterizes the HTTP contract between the Next.js app and the FastAPI backend: method, path, body, caching
// and error handling of every call. These expectations must survive the Clean Architecture refactor unchanged.
import { describe, expect, it } from "vitest";
import { notFound } from "next/navigation";
import * as api from "@/lib/api";
import { CASES, file } from "./support/apiCases";
import { BACKEND, fakeBackend } from "./support/backend";

describe("backend API client", () => {
  it.each(CASES)("$name sends $method $path", async ({ run, method, path, body }) => {
    const backend = fakeBackend({ [`${method} ${path.split("?")[0]}`]: { json: { ok: true } } });
    await run();
    expect(backend.calls).toHaveLength(1);
    const call = backend.last();
    expect(call.method).toBe(method);
    expect(call.path).toBe(path);
    expect(call.url.startsWith(BACKEND)).toBe(true);
    expect(call.init?.cache).toBe("no-store");
    if (body !== undefined) {
      expect(call.body).toEqual(body);
      expect(new Headers(call.init?.headers).get("Content-Type")).toBe("application/json");
    } else {
      expect(call.body).toBeUndefined();
    }
  });

  it("uploads topic images as multipart without a JSON content type", async () => {
    const backend = fakeBackend({ "POST /api/topics/t1/images": { json: { id: "t1" } } });
    await api.addTopicImage("t1", file);
    const call = backend.last();
    expect(call.path).toBe("/api/topics/t1/images");
    expect(call.body).toBeInstanceOf(FormData);
    expect((call.body as FormData).get("file")).toBeInstanceOf(File);
    expect(new Headers(call.init?.headers).has("Content-Type")).toBe(false);
  });

  it("returns parsed JSON for reads and mutations", async () => {
    fakeBackend({ "GET /api/topics": { json: [{ id: "t1" }] }, "POST /api/topics": { status: 201, json: { id: "t2" } } });
    await expect(api.getTopics()).resolves.toEqual([{ id: "t1" }]);
    await expect(api.createTopic("x")).resolves.toEqual({ id: "t2" });
  });

  it("returns undefined for 204 responses", async () => {
    fakeBackend({ "DELETE /api/topics/t1": { status: 204 } });
    await expect(api.deleteTopic("t1")).resolves.toBeUndefined();
  });

  it("surfaces the backend's error detail on failed mutations and uploads", async () => {
    fakeBackend({
      "POST /api/topics": { status: 409, json: { detail: "Topic name already exists" } },
      "POST /api/topics/t1/images": { status: 415, json: { detail: "Unsupported image type" } },
      "DELETE /api/items/i1": { status: 500, body: "not json" },
    });
    await expect(api.createTopic("x")).rejects.toThrow("Topic name already exists");
    await expect(api.addTopicImage("t1", file)).rejects.toThrow("Unsupported image type");
    await expect(api.deleteItem("i1")).rejects.toThrow("Backend request failed: /api/items/i1 (500)");
  });

  it("fails reads with the path and status", async () => {
    fakeBackend({ "GET /api/topics": { status: 503, json: { detail: "down" } } });
    await expect(api.getTopics()).rejects.toThrow("Backend request failed: /api/topics (503)");
  });

  it("turns a missing topic into Next's notFound()", async () => {
    fakeBackend({ "GET /api/topics/missing": { status: 404, json: { detail: "Topic not found" } } });
    await expect(api.getTopicById("missing")).rejects.toMatchObject({ notFound: true });
    expect(notFound).toHaveBeenCalledOnce();
  });

  it("passes the raw image response through for the proxy route", async () => {
    fakeBackend({ "GET /api/topics/t1/images/img": { body: new Uint8Array([1, 2, 3]), headers: { "Content-Type": "image/png" } } });
    const response = await api.fetchTopicImage("t1", "img");
    expect(response.ok).toBe(true);
    expect(response.headers.get("Content-Type")).toBe("image/png");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
  });
});
