/**
 * One selection, in the URL.
 *
 * The old dashboard kept `selected` in a useState that only the drawer
 * read, so nothing else on the page reacted to it, a reload lost it, and
 * a view could not be linked or shared. Putting view + selection in the
 * hash makes every panel able to both read the current focus and change
 * it, which is what turns seven sealed cards into one surface.
 */
import { useCallback, useEffect, useState } from "react";

export type View = "living" | "pending" | "graveyard" | "events";

export const VIEWS: { id: View; label: string }[] = [
  { id: "living", label: "Living" },
  { id: "pending", label: "Pending" },
  { id: "graveyard", label: "Graveyard" },
  { id: "events", label: "Events" },
];

export type Nav = {
  view: View;
  /** Entry id in focus, across every panel. */
  selected: string | null;
  /** Free-text filter, shared by the roster and the event log. */
  query: string;
};

const DEFAULT: Nav = { view: "living", selected: null, query: "" };

function parse(hash: string): Nav {
  const raw = hash.replace(/^#\/?/, "");
  const [view, search] = raw.split("?");
  const params = new URLSearchParams(search ?? "");
  const known = VIEWS.some((v) => v.id === view);
  return {
    view: known ? (view as View) : DEFAULT.view,
    selected: params.get("sel"),
    query: params.get("q") ?? "",
  };
}

function serialize(nav: Nav): string {
  const params = new URLSearchParams();
  if (nav.selected) params.set("sel", nav.selected);
  if (nav.query) params.set("q", nav.query);
  const search = params.toString();
  return `#/${nav.view}${search ? `?${search}` : ""}`;
}

export function useNav() {
  const [nav, setNav] = useState<Nav>(() => parse(window.location.hash));

  useEffect(() => {
    const onHash = () => setNav(parse(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((patch: Partial<Nav>) => {
    const next = { ...parse(window.location.hash), ...patch };
    const hash = serialize(next);
    if (hash !== window.location.hash) window.location.hash = hash;
    else setNav(next);
  }, []);

  /** Focus one entry, wherever it was clicked from. */
  const select = useCallback(
    (id: string | null) => go({ selected: id }),
    [go],
  );

  return { nav, go, select };
}

/** The href a link to one entry should carry, so middle-click works. */
export function entryHref(id: string, view: View = "living"): string {
  return serialize({ view, selected: id, query: "" });
}
