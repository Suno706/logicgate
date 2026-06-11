import { Sigma, Grid2x2, Activity, Lightbulb, Table, Sparkles, Info } from "lucide-react";
import type { RightTab } from "../types";
import { PropsPanel }  from "../panels/PropsPanel";
import { SmartPanel }  from "../panels/SmartPanel";
import { TruthPanel }  from "../panels/TruthPanel";
import { KmapPanel }   from "../panels/KmapPanel";
import { BoolPanel }   from "../panels/BoolPanel";
import { LedsPanel }   from "../panels/LedsPanel";
import { SignalPanel } from "../panels/SignalPanel";

interface Props {
  tab: RightTab;
  setTab: (t: RightTab) => void;
  selectedGateId: string | null;
}

const TABS: { id: RightTab; label: string; icon: React.ReactNode; title: string }[] = [
  { id: "props", label: "Props",  icon: <Info        size={14} />, title: "Gate properties" },
  { id: "truth", label: "Truth",  icon: <Table       size={14} />, title: "Truth table" },
  { id: "kmap",  label: "K-Map",  icon: <Grid2x2     size={14} />, title: "Karnaugh maps" },
  { id: "bool",  label: "Bool",   icon: <Sigma       size={14} />, title: "Boolean algebra" },
  { id: "sig",   label: "Sig",    icon: <Activity    size={14} />, title: "Signal levels" },
  { id: "leds",  label: "LEDs",   icon: <Lightbulb   size={14} />, title: "Output LED monitor" },
  { id: "smart", label: "Smart",  icon: <Sparkles    size={14} />, title: "Build / Suggest / Fault" },
];

export function RightPanel({ tab, setTab, selectedGateId }: Props) {
  return (
    <aside className="w-[320px] flex-shrink-0 bg-bg-800 border-l border-bg-600 flex flex-col overflow-hidden">
      <div className="flex border-b border-bg-600 flex-shrink-0 overflow-x-auto">
        {TABS.map(({ id, label, icon, title }) => (
          <button
            key={id}
            title={title}
            onClick={() => setTab(id)}
            className={`flex-1 min-w-[44px] flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium tracking-normal transition-colors border-b-2 ${
              tab === id
                ? "border-accent text-gray-100"
                : "border-transparent text-gray-500 hover:text-gray-200 hover:bg-bg-700/60"
            }`}
          >
            {icon}
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {tab === "props" && <PropsPanel  gateId={selectedGateId} />}
        {tab === "truth" && <TruthPanel  />}
        {tab === "kmap"  && <KmapPanel   />}
        {tab === "bool"  && <BoolPanel   />}
        {tab === "sig"   && <SignalPanel />}
        {tab === "leds"  && <LedsPanel   />}
        {tab === "smart" && <SmartPanel  />}
      </div>
    </aside>
  );
}
