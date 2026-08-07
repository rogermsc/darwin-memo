export type Finding = {
  code: string;
  severity: "error" | "warn";
  summary: string;
  evidence: string;
  fix: string;
};

export type TimelineRow = {
  tick: number;
  population: number;
  total_energy: number;
  deaths: number;
  merges: number;
  pending: number;
  delta: number;
};

export type Entry = {
  id: string;
  balance: number;
  kind: string;
  sources: string[];
  born_tick: number;
  age_ticks: number;
  last_settled_tick: number | null;
  uses: number;
  pinned: boolean;
  probation: number;
  question: string;
  ticks_to_starvation: number | null;
};

export type Grave = {
  id: string;
  question: string | null;
  cause: string;
  uses: number | null;
  sources: string[];
};

export type State = {
  tick: number;
  upkeep: number;
  counts: { alive: number; dead: number; pinned: number; pending: number };
  total_energy: number;
  doctor: Finding[];
  timeline: TimelineRow[];
  economics: {
    resource: {
      delta_total: number;
      decides: number;
      silent: number;
      settles: number;
    };
    energy: {
      credited: number;
      debited: number;
      net: number;
      upkeep_paid: number;
      upkeep_exact: boolean;
      upkeep_caveat: string;
    };
    population: { alive: number; dead: number };
  };
  entries: Entry[];
  graveyard: Grave[];
  pending: { id: string; query: string; born_tick: number; age_ticks: number }[];
};

import { useEffect, useState } from "react";

const POLL_MS = 2000;

export function useServerState() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetch("api/state");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (live) {
          setState(await response.json());
          setError(null);
        }
      } catch (caught) {
        if (live) setError(String(caught));
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return { state, error };
}

export async function fetchEntry(id: string) {
  const response = await fetch(`api/entry/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
