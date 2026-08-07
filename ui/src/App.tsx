import { useServerState } from "./api";
import { Header } from "./panels/Header";
import { DoctorBanner } from "./panels/DoctorBanner";

export default function App() {
  const { state, error } = useServerState();
  if (error) return <main className="panel">Cannot reach the server: {error}</main>;
  if (!state) return <main className="panel">Loading…</main>;
  return (
    <main>
      <Header state={state} />
      <DoctorBanner findings={state.doctor} />
    </main>
  );
}
