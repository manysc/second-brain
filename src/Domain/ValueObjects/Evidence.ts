/** The words an item or review candidate was extracted from. */
export type Evidence = {
  speaker: string | null;
  timestamp: string | null;
  quote: string;
  context: string | null;
};
