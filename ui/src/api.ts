/**
 * The server contract, plus the two things the old client got wrong.
 *
 * A failed poll used to replace the whole dashboard with an error string,
 * including the 503 the server returns BY DESIGN while a CLI `settle` or
 * `tick` holds the store lock. `useServerState` now keeps the last good
 * state and reports staleness alongside it, and it reads the server's own
 * message out of the body instead of stringifying a JS exception.
 *
 * Writes carry the per-process token the server embeds in the page.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type Finding = {
  code: string;
  severity: "error" | "warn";
  summary: string;
  evidence: string;
  fix: string;
};

export type TimelineRow = {
  tick: number;
  // A settlement that arrived after the last closed tick has no tick
  // to report population/energy/etc for yet -- it gets a trailing row
  // (see darwin_memo/observe.py timeline()) with these null and
  // `open: true`, rather than being silently dropped.
  population: number | null;
  total_energy: number | null;
  deaths: number | null;
  merges: number | null;
  pending: number | null;
  delta: number;
  open?: boolean;
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

export type Ticket = {
  id: string;
  query: string;
  born_tick: number;
  age_ticks: number;
};

export type Evidence = {
  events: number;
  ticks: number;
  settles: number;
  alive: number;
  graves: number;
  diagnosed: boolean;
};

export type StoreInfo = {
  path: string;
  name: string;
  max_energy: number;
  merge_threshold: number;
  admission_window: number;
};

export type State = {
  store: StoreInfo;
  tick: number;
  upkeep: number;
  counts: { alive: number; dead: number; pinned: number; pending: number };
  total_energy: number;
  evidence: Evidence;
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
  pending: Ticket[];
};

export type Note = {
  tick?: number | null;
  ts?: string | null;
  text?: string;
  event?: string;
  cause?: string;
  credit?: number;
  delta?: number;
  detail?: string;
  source?: string;
  deciding?: boolean;
};

export type Life = {
  id: string;
  status: "living" | "dead" | "merged";
  question: string | null;
  answer: string | null;
  kind: string | null;
  sources: string[];
  balance: number | null;
  uses: number | null;
  ticks_to_starvation: number | null;
  pinned: boolean;
  probation: number;
  juvenile: number;
  birth: {
    tick: number | null;
    ts: string | null;
    source: string | null;
    stake: number | null;
  };
  settlements: Note[];
  merged_into: string | null;
  cause_of_death: string | null;
  events: Note[];
};

export type LogEvent = {
  event: string;
  tick: number;
  ts: string;
  [key: string]: unknown;
};

const POLL_MS = 2000;

/** The write token, embedded in the document by darwin_memo/ui.py. */
function writeToken(): string {
  const meta = document.querySelector('meta[name="darwin-memo-token"]');
  return meta?.getAttribute("content") ?? "";
}

/** Read the server's own error message; fall back to the status code. */
async function describe(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (body && typeof body.error === "string") return body.error;
  } catch {
    // not JSON; the status line is all we have
  }
  return `HTTP ${response.status}`;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await describe(response));
  return response.json();
}

export type WriteAction =
  | "pin"
  | "unpin"
  | "forget"
  | "abandon"
  | "add"
  | "tick"
  | "settle";

export async function write(
  action: WriteAction,
  body: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const response = await fetch(`api/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Darwin-Memo-Token": writeToken(),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await describe(response));
  return response.json();
}

export type Server = {
  state: State | null;
  /** Why the last poll failed, if it did. The state above stays usable. */
  stale: string | null;
  /** Poll now -- called after a write so the page reflects it immediately. */
  refresh: () => void;
};

export function useServerState(): Server {
  const [state, setState] = useState<State | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const live = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await get<State>("api/state");
      if (!live.current) return;
      setState(next);
      setStale(null);
    } catch (caught) {
      // Keep the last good state. A CLI `settle` holding the lock for a
      // few milliseconds should not blank the operator's screen.
      if (live.current) setStale(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    live.current = true;
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live.current = false;
      clearInterval(timer);
    };
  }, [load]);

  return { state, stale, refresh: load };
}

export function fetchEntry(id: string): Promise<Life> {
  return get<Life>(`api/entry/${encodeURIComponent(id)}`);
}

export function fetchEvents(last = 300): Promise<{ events: LogEvent[] }> {
  return get<{ events: LogEvent[] }>(`api/events?last=${last}`);
}
