import { useCallback, useState } from "react";
import { useServerState, write, type WriteAction } from "./api";
import { useNav, VIEWS } from "./nav";
import { Rail } from "./panels/Rail";
import { Health } from "./panels/Health";
import { Roster } from "./panels/Roster";
import { Pending } from "./panels/Pending";
import { Graveyard } from "./panels/Graveyard";
import { Events } from "./panels/Events";
import { Detail } from "./panels/Detail";
import { Trend } from "./panels/Trend";

export default function App() {
  const { state, stale, refresh } = useServerState();
  const { nav, go, select } = useNav();
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ text: string; bad?: boolean } | null>(null);

  // One write path for the whole app: run it, say what happened, and pull
  // fresh state rather than waiting up to two seconds for the next poll.
  const act = useCallback(
    async (action: WriteAction, body: Record<string, unknown>, said: string) => {
      setBusy(true);
      try {
        const result = await write(action, body);
        const outcome = result.outcome;
        const rejected = result.pinned === false || result.unpinned === false ||
          result.settled === false || result.released === false ||
          (typeof outcome === "string" && outcome !== "buried");
        setFlash({
          text: rejected ? `${action}: ${outcome ?? "nothing changed; the target is no longer eligible"}` :
            typeof outcome === "string" ? `${action}: ${outcome}` : said,
          bad: rejected,
        });
        await refresh();
      } catch (caught) {
        setFlash({
          text: caught instanceof Error ? caught.message : String(caught),
          bad: true,
        });
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  if (!state) {
    return (
      <main className="boot">
        <h1>darwin-memo</h1>
        <p>{stale ? `Cannot reach the server: ${stale}` : "Reading the store…"}</p>
      </main>
    );
  }

  return (
    <div className="shell">
      <Rail state={state} nav={nav} go={go} busy={busy} act={act} />
      <main className="work" aria-busy={busy}>
        <Health state={state} go={go} select={select} />

        <nav className="views" aria-label="Views">
          {VIEWS.map((view) => {
            const count =
              view.id === "living"
                ? state.counts.alive
                : view.id === "pending"
                  ? state.counts.pending
                  : view.id === "graveyard"
                    ? state.counts.dead
                    : null;
            return (
              <button
                key={view.id}
                type="button"
                className={view.id === nav.view ? "view on" : "view"}
                aria-current={view.id === nav.view ? "page" : undefined}
                onClick={() => go({ view: view.id })}
              >
                {view.label}
                {count !== null && <span className="pill">{count}</span>}
              </button>
            );
          })}
        </nav>

        <div className="split">
          <section className="listing">
            {nav.view === "living" && (
              <Roster state={state} nav={nav} go={go} select={select} />
            )}
            {nav.view === "pending" && (
              <Pending state={state} select={select} busy={busy} act={act} />
            )}
            {nav.view === "graveyard" && (
              <Graveyard state={state} nav={nav} select={select} />
            )}
            {nav.view === "events" && <Events nav={nav} go={go} select={select} />}
          </section>

          <Detail
            id={nav.selected}
            state={state}
            go={go}
            select={select}
            busy={busy}
            act={act}
          />
        </div>

        <Trend state={state} />
      </main>

      {flash && (
        <div
          className={flash.bad ? "flash bad" : "flash"}
          role="status"
          onAnimationEnd={() => setFlash(null)}
        >
          {flash.text}
        </div>
      )}
      {stale && (
        <div className="stale" role="status">
          showing the last good read &mdash; {stale}
        </div>
      )}
    </div>
  );
}
