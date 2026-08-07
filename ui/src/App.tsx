import { useState } from "react";
import { useServerState } from "./api";
import { Header } from "./panels/Header";
import { DoctorBanner } from "./panels/DoctorBanner";
import { Timeline } from "./panels/Timeline";
import { LivingTable } from "./panels/LivingTable";

export default function App() {
  const { state, error } = useServerState();
  // Selected entry id: not read until Task 8 mounts the drawer.
  const [, setSelected] = useState<string | null>(null);
  if (error) return <main className="panel">Cannot reach the server: {error}</main>;
  if (!state) return <main className="panel">Loading…</main>;
  return (
    <main>
      <Header state={state} />
      <DoctorBanner findings={state.doctor} />
      <Timeline rows={state.timeline} />
      <LivingTable entries={state.entries} onSelect={setSelected} />
    </main>
  );
}
