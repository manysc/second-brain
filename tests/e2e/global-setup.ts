import { seed } from "./fixture";

export default function globalSetup() {
  const run = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  process.env.E2E_SEED = JSON.stringify(seed(run));
}
