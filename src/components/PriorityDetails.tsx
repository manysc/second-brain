"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { EffectivePriorityInfo } from "@/lib/domain";
import { PriorityBadge } from "@/components/PriorityBadge";

type PriorityDetailsContextValue = { open: boolean; toggle: () => void };

const PriorityDetailsContext = createContext<PriorityDetailsContextValue | null>(null);

function usePriorityDetails() {
  const value = useContext(PriorityDetailsContext);
  if (!value) throw new Error("Priority details components must be used inside PriorityDetailsProvider");
  return value;
}

export function PriorityDetailsProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <PriorityDetailsContext.Provider value={{ open, toggle: () => setOpen((current) => !current) }}>
      {children}
    </PriorityDetailsContext.Provider>
  );
}

export function PriorityDetailsBadge({ priority }: { priority: EffectivePriorityInfo | null }) {
  const { open, toggle } = usePriorityDetails();
  return (
    <button
      type="button"
      className="priority-toggle"
      aria-expanded={open}
      aria-controls="priority-details"
      title={open ? "Hide priority details" : "Show priority details"}
      onClick={toggle}
    >
      <PriorityBadge priority={priority} />
    </button>
  );
}

export function PriorityDetailsPanel({ children }: { children: ReactNode }) {
  const { open } = usePriorityDetails();
  return open ? <div id="priority-details">{children}</div> : null;
}
