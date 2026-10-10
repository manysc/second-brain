import { cleanup, seeded } from "./fixture";

export default function globalTeardown() {
  cleanup(seeded().run);
}
