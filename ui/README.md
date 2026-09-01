# darwin-memo dashboard

The read-only dashboard `darwin-memo ui` serves: population and energy over
time, the graveyard split by cause of death, the resource-versus-upkeep
accounting, pending tickets, and whatever `darwin-memo doctor` has to say
about the store.

Vite + React + TypeScript + Recharts. It reads one memory file through a
loopback-only HTTP server with no mutation endpoints, which is why there is
nothing here to authenticate.

## Using it

You do not need any of this to run the dashboard. A released wheel ships the
built bundle:

```bash
pip install darwin-memo
darwin-memo ui memory.json
```

## Working on it

From a source checkout the bundle is not present -- `darwin_memo/data/ui/` is
gitignored and built at release time -- so `darwin-memo ui` serves a
placeholder page until you build it:

```bash
cd ui
npm install
npm run build          # writes ../darwin_memo/data/ui/
npm run dev            # or: dev server on :5173, proxying /api to :8787
```

For `npm run dev` you need the Python side serving the data:

```bash
darwin-memo ui memory.json --port 8787 --no-open
```

Python-only contributors never need node: the placeholder page exists so the
CLI degrades honestly instead of erroring, and CI does not build the bundle.
`.github/workflows/release.yml` does, before `python -m build`.

## Layout

- `src/api.ts` — typed against the payloads `darwin_memo/ui.py` serves
- `src/panels/` — Timeline, LivingTable, Graveyard, Economics, EventStream,
  EntryDrawer, DoctorBanner, Header
- `src/theme.css` — the whole visual system; there is no CSS framework
- `vite.config.ts` — `outDir` points into the Python package, `base` is
  relative so the bundle works from any mount path

`package.json` is `private` and its `0.0.0` is not the package version:
this bundle ships inside the Python wheel and is versioned by it. Deliberately
left alone so there is no second version to keep in step with the four that
`tests/test_version_agreement.py` already pins.

The server, its Host-header check, and the payload shapes are in
`darwin_memo/ui.py`; `tests/test_ui.py` covers both.
