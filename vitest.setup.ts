import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Next's server-only modules have no runtime outside the framework; these stand-ins record what was called.
// redirect()/notFound() throw like the real ones, so code after them does not run.
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw Object.assign(new Error(`NEXT_REDIRECT ${url}`), { redirectUrl: url });
  }),
  notFound: vi.fn(() => {
    throw Object.assign(new Error("NEXT_NOT_FOUND"), { notFound: true });
  }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

afterEach(() => {
  if (typeof document !== "undefined") cleanup();
});
