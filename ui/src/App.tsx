import { useState } from "react";
import { useServerState } from "./api";
import { Header } from "./panels/Header";
import { DoctorBanner } from "./panels/DoctorBanner";
import { Timeline } from "./panels/Timeline";
import { LivingTable } from "./panels/LivingTable";
import { Economics } from "./panels/Economics";
import { Graveyard } from "./panels/Graveyard";
import { EventStream } from "./panels/EventStream";
import { EntryDrawer } from "./panels/EntryDrawer";

export default function App() {
  const { state, error } = useServerState();
  const [selected, setSelected] = useState<string | null>(null);
  if (error) return <main className="panel">Cannot reach the server: {error}</main>;
  if (!state) return <main className="panel">Loading…</main>;
  return (
    <main>
      <Header state={state} />
      <DoctorBanner findings={state.doctor} />
      <Timeline rows={state.timeline} />
      <LivingTable entries={state.entries} onSelect={setSelected} />
      <Economics report={state.economics} />
      <Graveyard graves={state.graveyard} />
      <EventStream />
      {selected && <EntryDrawer id={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
