import { notFound } from "next/navigation";
import { NotFoundError } from "@/Application/Errors";

/** For pages: a use case reporting "no such thing" becomes Next's 404 page; any other failure still surfaces. */
export async function orNotFound<T>(loading: Promise<T>): Promise<T> {
  try {
    return await loading;
  } catch (error) {
    if (error instanceof NotFoundError) notFound();
    throw error;
  }
}
