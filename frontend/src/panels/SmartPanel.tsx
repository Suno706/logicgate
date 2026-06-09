import { useEffect, useState } from "react";
import {
  buildQuestion, analyzeFaults, suggestConnection, analyzeMinimize, askQuestion,
  submitFeedback, getLearningStats, retrainIntent,
} from "../api";
import { ThumbsUp, ThumbsDown, RefreshCw, GraduationCap } from "lucide-react";
import type { Fault, ConnectionSuggestion } from "../types";
import { useCircuitState, useCircuitDispatch } from "../store";

type SmartTab = "ask" | "build" | "suggest" | "fault" | "min";

const EXAMPLES = [
  "half adder",
  "full adder using only NAND",
  "4-to-1 mux",
  "3-to-8 decoder",
  "JK flip flop",
  "bcd to 7 segment",
  "4 bit ripple carry adder",
  "output 1 when exactly two of A B C D are 1",
];

export function SmartPanel() {
  const state    = useCircuitState();
  const dispatch = useCircuitDispatch();
  const { circuit } = state;

  const [tab, setTab] = useState<SmartTab>("ask");

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Sub-tabs */}
      <div className="flex border-b border-bg-600 flex-shrink-0">
        {(["ask", "build", "suggest", "fault", "min"] as SmartTab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 py-1.5 text-[8px] font-mono uppercase tracking-widest transition-all border-b-2 ${
              tab === t
                ? "border-accent text-accent bg-accent/5"
                : "border-transparent text-gray-600 hover:text-gray-400"
            }`}>
            {t === "ask" ? "Ask" : t === "build" ? "Build" : t === "suggest" ? "Suggest" : t === "fault" ? "Fault" : "Minimize"}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "ask"     && <AskTab circuit={circuit} dispatch={dispatch} />}
        {tab === "build"   && <BuildTab circuit={circuit} dispatch={dispatch} />}
        {tab === "suggest" && <SuggestTab circuit={circuit} dispatch={dispatch} />}
        {tab === "fault"   && <FaultTab circuit={circuit} />}
        {tab === "min"     && <MinTab circuit={circuit} />}
      </div>
    </div>
  );
}

/* ─── Ask Tab — free-form NL Q&A over the current circuit ───────────────── */
interface ChatMsg {
  role: "user" | "bot";
  text: string;
  intent?: string;
  conf?: number;
  source?: "ml" | "regex" | "fallback" | "knowledge_base";
  queryId?: string;
  feedback?: "up" | "down" | null;
}

function AskTab({ circuit, dispatch }: { circuit: any; dispatch: any }) {
  const [q, setQ]           = useState("");
  const [loading, setL]     = useState(false);
  const [history, setHist]  = useState<ChatMsg[]>([]);
  const [stats, setStats]   = useState<{ total: number; helpful: number; corrected: number } | null>(null);
  const [retraining, setRT] = useState(false);

  // Refresh learning stats on first render + every 30s
  useEffect(() => {
    const refresh = () => {
      getLearningStats().then((s) =>
        setStats({ total: s.total_queries, helpful: s.helpful, corrected: s.corrected })
      ).catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, []);

  async function doRetrain() {
    setRT(true);
    try {
      const r = await retrainIntent();
      setHist((h) => [...h, { role: "bot", text: `[Learning] ${r.message}` }]);
    } catch (e) {
      setHist((h) => [...h, { role: "bot", text: `[Learning] Failed: ${e instanceof Error ? e.message : e}` }]);
    } finally { setRT(false); }
  }

  async function send(text: string) {
    const t = text.trim();
    if (!t) return;
    setHist((h) => [...h, { role: "user", text: t }]);
    setQ(""); setL(true);
    try {
      const r = await askQuestion(t, circuit);
      const meta = { intent: r.intent, conf: r.intent_confidence, source: r.ml_source,
                     queryId: r.query_id, feedback: null as null };
      if (r.circuit && r.circuit.gates.length > 0) {
        dispatch({ type: "SET_CIRCUIT", circuit: r.circuit });
        setHist((h) => [...h, {
          role: "bot",
          text: `Built — ${r.circuit!.gates.length} gates, ${r.circuit!.wires.length} wires.`,
          ...meta,
        }]);
      } else if (r.answer) {
        setHist((h) => [...h, { role: "bot", text: r.answer!, ...meta }]);
      } else {
        setHist((h) => [...h, { role: "bot", text: "(no response)", ...meta }]);
      }
    } catch (e) {
      setHist((h) => [...h, { role: "bot", text: `Error: ${e instanceof Error ? e.message : e}` }]);
    } finally { setL(false); }
  }

  const examples = [
    "what does this circuit do",
    "how many gates",
    "any faults",
    "minimize this",
    "build a 4-bit adder",
    "output is 1 when A and B differ",
  ];

  return (
    <div className="p-3 space-y-3 flex flex-col">
      <div className="space-y-1.5 max-h-[260px] overflow-y-auto">
        {history.length === 0 && (
          <div className="text-[9px] text-gray-600 font-mono leading-relaxed">
            Ask anything about your circuit, or describe one to build.
          </div>
        )}
        {history.map((m, i) => (
          <div key={i} className={`text-[10px] font-mono leading-relaxed rounded p-2 ${
            m.role === "user"
              ? "bg-accent/10 border border-accent/30 text-gray-200"
              : "bg-bg-700 border border-bg-600 text-gray-300"
          }`}>
            {m.role === "bot" && m.intent && (
              <div className="flex items-center gap-1.5 mb-1 text-[7px] uppercase tracking-widest">
                <span className={`px-1 py-0.5 rounded ${
                  m.source === "ml" ? "bg-accent/20 text-accent"
                  : m.source === "knowledge_base" ? "bg-purple-500/20 text-purple-400"
                  : m.source === "regex" ? "bg-warn/20 text-warn"
                  : "bg-gray-700 text-gray-500"
                }`}>
                  {m.source === "ml" ? "ML"
                   : m.source === "knowledge_base" ? "KB"
                   : m.source === "regex" ? "rule" : "fallback"}
                </span>
                <span className="text-gray-500">intent: {m.intent}</span>
                {m.conf !== undefined && m.conf > 0 && (
                  <span className="text-gray-600">· {Math.round(m.conf * 100)}%</span>
                )}
              </div>
            )}
            <div className="whitespace-pre-wrap break-words">{m.text}</div>
            {m.role === "bot" && m.queryId && (
              <div className="flex items-center gap-2 mt-2 pt-1.5 border-t border-bg-600">
                <span className="text-[8px] font-mono text-gray-600 uppercase tracking-widest">
                  {m.feedback ? "Thanks — ML will learn from this." : "Was this useful?"}
                </span>
                <div className="flex-1" />
                <button
                  title="Helpful — confirms this intent classification"
                  disabled={!!m.feedback}
                  onClick={async () => {
                    try { await submitFeedback({ query_id: m.queryId!, helpful: true }); } catch {}
                    setHist((hh) => hh.map((mm, j) => j === i ? { ...mm, feedback: "up" } : mm));
                  }}
                  className={`p-1 rounded ${m.feedback === "up" ? "bg-ok/20 text-ok" : "text-gray-500 hover:text-ok hover:bg-bg-800"} disabled:cursor-default transition-colors`}
                >
                  <ThumbsUp size={11} />
                </button>
                <button
                  title="Not useful — flags this for retraining"
                  disabled={!!m.feedback}
                  onClick={async () => {
                    try { await submitFeedback({ query_id: m.queryId!, helpful: false }); } catch {}
                    setHist((hh) => hh.map((mm, j) => j === i ? { ...mm, feedback: "down" } : mm));
                  }}
                  className={`p-1 rounded ${m.feedback === "down" ? "bg-err/20 text-err" : "text-gray-500 hover:text-err hover:bg-bg-800"} disabled:cursor-default transition-colors`}
                >
                  <ThumbsDown size={11} />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      <div>
        <textarea
          className="w-full bg-bg-700 border border-bg-600 rounded px-2.5 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-accent resize-none h-16 placeholder-gray-600"
          placeholder="Ask… e.g. 'what does this do' or 'build a JK flip-flop'"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey || !e.shiftKey)) { e.preventDefault(); send(q); } }}
        />
        <button
          onClick={() => send(q)}
          disabled={loading || !q.trim()}
          className="mt-1.5 w-full py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-mono font-bold disabled:opacity-40 transition-all"
        >
          {loading ? "Thinking…" : "Send →"}
        </button>
      </div>

      <div>
        <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-1">Try</div>
        <div className="space-y-0.5">
          {examples.map((ex) => (
            <button key={ex} onClick={() => send(ex)}
              className="w-full text-left text-[9px] font-mono text-gray-500 hover:text-accent hover:bg-bg-700 rounded px-2 py-1 transition-colors">
              {ex}
            </button>
          ))}
        </div>
      </div>

      {/* ─── Online-learning footer ──────────────────────────────────────── */}
      <div className="border-t border-bg-600 pt-2 mt-2">
        <div className="flex items-center gap-1.5 mb-1">
          <GraduationCap size={10} className="text-accent" />
          <span className="text-[8px] font-mono uppercase tracking-widest text-gray-500">Learning</span>
        </div>
        {stats ? (
          <div className="text-[9px] font-mono text-gray-600 leading-relaxed">
            {stats.total} queries logged · <span className="text-ok">{stats.helpful} confirmed</span>
            {stats.corrected > 0 && <> · <span className="text-warn">{stats.corrected} corrected</span></>}
          </div>
        ) : (
          <div className="text-[9px] font-mono text-gray-700">Loading stats…</div>
        )}
        <button
          onClick={doRetrain}
          disabled={retraining}
          title="Wipe the trained classifier so the next /api/ask retrains it with your feedback merged in (×5 weight on confirmed samples)."
          className="mt-1.5 w-full flex items-center justify-center gap-1.5 py-1.5 rounded bg-bg-700 hover:bg-accent/20 border border-bg-600 hover:border-accent text-[9px] font-mono font-bold text-gray-300 hover:text-accent disabled:opacity-40 transition-all"
        >
          <RefreshCw size={10} className={retraining ? "animate-spin" : ""} />
          {retraining ? "Resetting…" : "Retrain on my feedback"}
        </button>
      </div>
    </div>
  );
}

/* ─── Build Tab ─────────────────────────────────────────────────────────── */
function BuildTab({ dispatch }: { circuit?: any; dispatch: any }) {
  const [q, setQ]         = useState("");
  const [loading, setL]   = useState(false);
  const [error, setErr]   = useState<string | null>(null);
  const [info, setInfo]   = useState<any>(null);
  const [showStruct, setShowStruct] = useState(false);

  // Structured-input fallback state
  type Mode = "template" | "expr" | "truth";
  const [sMode,     setSMode]     = useState<Mode>("template");
  const [sTemplate, setSTemplate] = useState<string>("half adder");
  const [sExpr,     setSExpr]     = useState<string>("");
  const [sGates,    setSGates]    = useState<string[]>([]);  // empty = mixed
  // Truth-table state
  const [tInputs,   setTInputs]   = useState<number>(2);
  const [tBits,     setTBits]     = useState<(0 | 1)[]>([0, 0, 0, 1]); // default = AND

  const TEMPLATES = [
    "half adder", "full adder", "full adder using half adder",
    "2 to 1 mux", "4 to 1 mux", "majority gate",
    "d flip flop", "sr latch", "jk flip flop", "t flip flop",
    "decoder 2 to 4", "encoder 4 to 2",
    "2 bit adder", "4 bit adder", "8 bit adder",
    "2 bit comparator", "parity",
  ];
  const GATE_OPTIONS = ["NAND", "NOR", "AND", "OR", "NOT", "XOR", "XNOR"];

  async function build(question: string) {
    const q2 = question.trim();
    if (!q2) return;
    setL(true); setErr(null); setInfo(null);
    try {
      const r = await buildQuestion(q2);
      if (r.circuit) {
        dispatch({ type: "SET_CIRCUIT", circuit: r.circuit });
        setInfo(r.info ?? null);
        setShowStruct(false);
      } else if (r.answer) {
        setErr(r.answer);
        // Pop the structured form so the user has a no-NL way out.
        setShowStruct(true);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setShowStruct(true);
    } finally { setL(false); }
  }

  function buildFromStruct() {
    let q2 = "";
    if (sMode === "expr" && sExpr.trim()) {
      q2 = `build ${sExpr.trim()}`;
    } else if (sMode === "truth") {
      // Convert truth-table bits to an SOP boolean expression that the
      // backend's boolean parser already understands.
      const names = "ABCDEFGH".slice(0, tInputs).split("");
      const minterms: string[] = [];
      for (let i = 0; i < tBits.length; i++) {
        if (tBits[i] !== 1) continue;
        const terms = names.map((n, idx) => {
          const bit = (i >> (tInputs - 1 - idx)) & 1;
          return bit ? n : "~" + n;
        });
        minterms.push("(" + terms.join(" & ") + ")");
      }
      if (!minterms.length) { setErr("Truth table has no 1-outputs — nothing to build."); return; }
      q2 = `build ${minterms.join(" | ")}`;
    } else {
      q2 = `build ${sTemplate}`;
    }
    if (sGates.length > 0) {
      q2 += ` using ${sGates.join(" and ")}`;
    }
    setQ(q2);
    build(q2);
  }

  function resizeTruthTable(n: number) {
    setTInputs(n);
    setTBits(Array(1 << n).fill(0) as (0 | 1)[]);
  }
  function toggleBit(i: number) {
    setTBits((prev) => prev.map((b, idx) => (idx === i ? ((b ^ 1) as 0 | 1) : b)));
  }

  function toggleGate(g: string) {
    setSGates((prev) => prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]);
  }

  return (
    <div className="p-3 space-y-3">
      <div>
        <textarea
          className="w-full bg-bg-700 border border-bg-600 rounded px-2.5 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-accent resize-none h-20 placeholder-gray-600"
          placeholder="Describe a circuit…&#10;e.g. full adder using only NAND"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) build(q); }}
        />
        <button
          onClick={() => build(q)}
          disabled={loading || !q.trim()}
          className="mt-1.5 w-full py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-mono font-bold disabled:opacity-40 transition-all"
        >
          {loading ? "Building…" : "Build circuit →"}
        </button>
        <button
          onClick={() => setShowStruct((s) => !s)}
          className="mt-1 w-full py-1 rounded bg-bg-700 hover:bg-bg-600 text-gray-400 hover:text-accent text-[10px] font-mono border border-bg-600 transition-all"
        >
          {showStruct ? "Hide structured form ▲" : "Can't describe it? Use structured form ▼"}
        </button>
      </div>

      {showStruct && (
        <div className="bg-bg-700/40 border border-bg-600 rounded p-2.5 space-y-2.5">
          <div className="text-[8px] font-mono uppercase tracking-widest text-gray-500">
            Structured build — no NL needed
          </div>

          {/* Mode tabs */}
          <div className="flex gap-1 text-[9px] font-mono">
            {(["template", "expr", "truth"] as Mode[]).map((m) => (
              <button key={m} onClick={() => setSMode(m)}
                className={`flex-1 py-1 rounded border transition-all ${
                  sMode === m
                    ? "bg-accent/25 border-accent text-accent"
                    : "bg-bg-800 border-bg-600 text-gray-500 hover:border-gray-500"
                }`}
              >
                {m === "template" ? "Template" : m === "expr" ? "Boolean" : "Truth Table"}
              </button>
            ))}
          </div>

          {sMode === "template" && (
            <div>
              <label className="text-[9px] font-mono text-gray-500 block mb-1">Pick a circuit</label>
              <select
                value={sTemplate}
                onChange={(e) => setSTemplate(e.target.value)}
                className="w-full bg-bg-800 border border-bg-600 rounded px-2 py-1 text-[10px] font-mono text-gray-200 focus:outline-none focus:border-accent"
              >
                {TEMPLATES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          )}

          {sMode === "expr" && (
            <div>
              <label className="text-[9px] font-mono text-gray-500 block mb-1">
                Boolean expression
              </label>
              <input
                type="text"
                value={sExpr}
                onChange={(e) => setSExpr(e.target.value)}
                placeholder="e.g. (A&B) | (~A&C) | (B^C)"
                className="w-full bg-bg-800 border border-bg-600 rounded px-2 py-1 text-[10px] font-mono text-gray-200 focus:outline-none focus:border-accent placeholder-gray-700"
              />
              <div className="text-[8px] font-mono text-gray-600 mt-1">
                Operators: <code>&amp;</code> = AND, <code>|</code> = OR, <code>~</code> = NOT, <code>^</code> = XOR
              </div>
            </div>
          )}

          {sMode === "truth" && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-[9px] font-mono text-gray-500">
                <span>Inputs:</span>
                {[2, 3, 4].map((n) => (
                  <button key={n} onClick={() => resizeTruthTable(n)}
                    className={`px-2 py-0.5 rounded border ${
                      tInputs === n
                        ? "bg-accent/25 border-accent text-accent"
                        : "bg-bg-800 border-bg-600 text-gray-500 hover:border-gray-500"
                    }`}
                  >{n}</button>
                ))}
                <span className="ml-auto">Click Y to toggle</span>
              </div>
              <div className="bg-bg-800 border border-bg-600 rounded p-1.5 max-h-44 overflow-y-auto">
                <table className="w-full text-[9px] font-mono">
                  <thead>
                    <tr className="text-gray-600">
                      {"ABCDEFGH".slice(0, tInputs).split("").map((n) => (
                        <th key={n} className="px-1 text-center">{n}</th>
                      ))}
                      <th className="px-1 text-center text-accent">Y</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tBits.map((b, i) => (
                      <tr key={i} className="hover:bg-bg-700/40">
                        {Array.from({length: tInputs}).map((_, k) => (
                          <td key={k} className="px-1 text-center text-gray-500">
                            {(i >> (tInputs - 1 - k)) & 1}
                          </td>
                        ))}
                        <td className="px-1 text-center">
                          <button onClick={() => toggleBit(i)}
                            className={`w-5 h-4 rounded font-bold ${
                              b ? "bg-accent/25 text-accent" : "bg-bg-700 text-gray-600 hover:text-gray-300"
                            }`}
                          >{b}</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Always-visible gate restriction */}
          <div>
            <label className="text-[9px] font-mono text-gray-500 block mb-1">
              Restrict to gates (optional)
            </label>
            <div className="flex flex-wrap gap-1">
              {GATE_OPTIONS.map((g) => (
                <button
                  key={g}
                  onClick={() => toggleGate(g)}
                  className={`px-2 py-0.5 rounded text-[9px] font-mono border transition-all ${
                    sGates.includes(g)
                      ? "bg-accent/25 border-accent text-accent"
                      : "bg-bg-800 border-bg-600 text-gray-500 hover:border-gray-500"
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
            {sGates.length > 0 && (
              <button onClick={() => setSGates([])}
                className="text-[8px] text-gray-600 hover:text-accent mt-1">clear</button>
            )}
          </div>

          <button
            onClick={buildFromStruct}
            disabled={loading}
            className="w-full py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-[10px] font-mono font-bold disabled:opacity-40"
          >
            Build from form →
          </button>
        </div>
      )}

      {error && (
        <div className="bg-bg-700 border border-bg-600 rounded p-2.5 text-[10px] font-mono text-gray-400 whitespace-pre-wrap leading-relaxed">
          {error}
        </div>
      )}

      {info && (
        <div className="bg-bg-700 border border-bg-600 rounded p-2.5 text-[9px] font-mono text-gray-500 space-y-0.5">
          {info.gate_count != null && <div>Gates: <span className="text-gray-300">{info.gate_count}</span></div>}
          {info.wire_count != null && <div>Wires: <span className="text-gray-300">{info.wire_count}</span></div>}
          {info.input_vars?.length > 0 && <div>Inputs: <span className="text-gray-300">{info.input_vars.join(", ")}</span></div>}
          {info.target_gates && <div>Gates used: <span className="text-gray-300">{info.target_gates.join(", ")}</span></div>}
          {info.simplified && <div className="mt-1 text-gray-600 break-all">= {info.simplified}</div>}
        </div>
      )}

      <div>
        <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600 mb-1.5">Examples</div>
        <div className="space-y-0.5">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => { setQ(ex); build(ex); }}
              className="w-full text-left text-[9px] font-mono text-gray-500 hover:text-accent hover:bg-bg-700 rounded px-2 py-1 transition-colors">
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ─── Suggest Tab ───────────────────────────────────────────────────────── */
function SuggestTab({ circuit, dispatch }: { circuit: any; dispatch: any }) {
  const [loading, setL]   = useState(false);
  const [suggs, setSuggs] = useState<ConnectionSuggestion[]>([]);
  const [error, setErr]   = useState<string | null>(null);

  const byId = new Map(circuit.gates.map((g: any) => [g.id, g]));

  async function fetchSuggs() {
    setL(true); setErr(null);
    try {
      const r = await suggestConnection(circuit, 8);
      setSuggs(r.suggestions ?? []);
      if (!r.suggestions?.length) setErr("No suggestions at this time — try adding more gates first.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setL(false); }
  }

  function addWire(s: ConnectionSuggestion) {
    dispatch({
      type: "ADD_WIRE",
      wire: { id: `w${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, from_gate: s.from_gate, from_pin: s.from_pin, to_gate: s.to_gate, to_pin: s.to_pin },
    });
    setSuggs((prev) => prev.filter((x) => x !== s));
  }

  function gName(id: string) {
    const g = byId.get(id) as any;
    return g ? (g.label || g.type) : id;
  }

  return (
    <div className="p-3 space-y-3">
      <button
        onClick={fetchSuggs}
        disabled={loading || !circuit.gates.length}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all"
      >
        {loading ? "Analysing…" : "Get wire suggestions →"}
      </button>

      {error && <div className="text-[9px] font-mono text-gray-600">{error}</div>}

      {suggs.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600">
            {suggs.length} suggestion{suggs.length !== 1 ? "s" : ""}
          </div>
          {suggs.map((s, i) => (
            <div key={i} className="bg-bg-700 border border-bg-600 rounded p-2 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-gray-300">
                  {gName(s.from_gate)} → {gName(s.to_gate)}
                </span>
                <span className="text-[9px] font-mono text-gray-600">
                  {(s.score * 100).toFixed(0)}%
                </span>
              </div>
              {s.reason && <div className="text-[9px] font-mono text-gray-600">{s.reason}</div>}
              <button
                onClick={() => addWire(s)}
                className="text-[9px] font-mono text-accent hover:text-accent-hover"
              >
                + Add wire
              </button>
            </div>
          ))}
        </div>
      )}

      {!suggs.length && !error && !loading && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-4">
          Click the button above to get intelligent wire connection suggestions based on your circuit structure.
        </div>
      )}
    </div>
  );
}

/* ─── Fault Tab ─────────────────────────────────────────────────────────── */
const SEV_COLOR: Record<string, string> = {
  CRITICAL: "text-err border-err/40 bg-err/5",
  HIGH:     "text-orange-400 border-orange-400/40 bg-orange-400/5",
  MEDIUM:   "text-warn border-warn/40 bg-warn/5",
  LOW:      "text-gray-400 border-gray-600 bg-bg-700",
};

function FaultTab({ circuit }: { circuit: any }) {
  const [loading, setL]     = useState(false);
  const [faults, setFaults] = useState<Fault[]>([]);
  const [checked, setChecked] = useState(false);
  const [error, setErr]     = useState<string | null>(null);

  async function runCheck() {
    setL(true); setErr(null);
    try {
      const r = await analyzeFaults(circuit);
      setFaults(r.faults ?? []);
      setChecked(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setL(false); }
  }

  const bySev = {
    CRITICAL: faults.filter((f) => f.severity === "CRITICAL"),
    HIGH:     faults.filter((f) => f.severity === "HIGH"),
    MEDIUM:   faults.filter((f) => f.severity === "MEDIUM"),
    LOW:      faults.filter((f) => f.severity === "LOW"),
  };

  return (
    <div className="p-3 space-y-3">
      <button
        onClick={runCheck}
        disabled={loading || !circuit.gates.length}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all"
      >
        {loading ? "Checking…" : "Run fault detection →"}
      </button>

      {error && <div className="text-[9px] font-mono text-err">{error}</div>}

      {checked && (
        <div className={`p-2 rounded border text-xs font-mono font-bold ${
          faults.length === 0 ? "bg-ok/5 border-ok/30 text-ok" : "bg-err/5 border-err/30 text-err"
        }`}>
          {faults.length === 0 ? "✓ No faults detected" : `✗ ${faults.length} fault${faults.length !== 1 ? "s" : ""} found`}
        </div>
      )}

      {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map((sev) => {
        const items = bySev[sev];
        if (!items.length) return null;
        return (
          <div key={sev} className="space-y-1">
            <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600">{sev}</div>
            {items.map((f, i) => (
              <div key={i} className={`border rounded p-2 space-y-0.5 ${SEV_COLOR[sev]}`}>
                <div className="text-[10px] font-mono font-bold">{f.type}</div>
                <div className="text-[9px] font-mono opacity-80">{f.message}</div>
                {f.gate_id && <div className="text-[8px] opacity-60">Gate: {f.gate_id}</div>}
              </div>
            ))}
          </div>
        );
      })}

      {!checked && !loading && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-4">
          Click the button above to check your circuit for structural faults, dangling wires, and logic errors.
        </div>
      )}
    </div>
  );
}

/* ─── Minimize Tab ──────────────────────────────────────────────────────── */
function MinTab({ circuit }: { circuit: any }) {
  const [loading, setL]   = useState(false);
  const [result, setRes]  = useState<any>(null);
  const [error, setErr]   = useState<string | null>(null);

  async function run() {
    setL(true); setErr(null);
    try {
      const r = await analyzeMinimize(circuit);
      // Store the full response — MinTab reads current_gate_count,
      // efficiency_score, benchmark, and suggestions from it.
      setRes(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setL(false); }
  }

  return (
    <div className="p-3 space-y-3">
      <button
        onClick={run}
        disabled={loading || !circuit.gates.length}
        className="w-full py-1.5 rounded bg-bg-700 hover:bg-bg-600 border border-bg-600 text-xs font-mono text-gray-300 disabled:opacity-40 transition-all"
      >
        {loading ? "Analysing…" : "Analyse minimization →"}
      </button>

      {error && <div className="text-[9px] font-mono text-err">{error}</div>}

      {result && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-bg-700 border border-bg-600 rounded p-2 text-center">
              <div className="text-[9px] font-mono text-gray-600">Gates</div>
              <div className="text-lg font-mono font-bold text-gray-200">{result.current_gate_count ?? "—"}</div>
            </div>
            <div className="bg-bg-700 border border-bg-600 rounded p-2 text-center">
              <div className="text-[9px] font-mono text-gray-600">Efficiency</div>
              <div className={`text-lg font-mono font-bold ${
                (result.efficiency_score ?? 0) >= 80 ? "text-ok" : (result.efficiency_score ?? 0) >= 50 ? "text-warn" : "text-err"
              }`}>
                {result.efficiency_score != null ? `${result.efficiency_score}%` : "—"}
              </div>
            </div>
          </div>

          {result.benchmark && (
            <div className="text-[9px] font-mono text-gray-600">
              Benchmark:{" "}
              {typeof result.benchmark === "object"
                ? `mean ${Math.round((result.benchmark.mean ?? 0) * 10) / 10}, median ${result.benchmark.median ?? "?"}, min ${result.benchmark.min ?? "?"} gates`
                : result.benchmark}
            </div>
          )}

          {result.suggestions?.length > 0 && (
            <div className="space-y-1">
              <div className="text-[8px] font-mono uppercase tracking-widest text-gray-600">Suggestions</div>
              {result.suggestions.map((s: any, i: number) => {
                // Backend returns suggestions as either strings (legacy) or
                // objects { type, description, current_gates, estimated_gates, savings, confidence }.
                const text = typeof s === "string" ? s : (s.description || s.message || JSON.stringify(s));
                const savings = typeof s === "object" ? s.savings : null;
                const conf    = typeof s === "object" ? s.confidence : null;
                return (
                  <div key={i} className="bg-bg-700 border border-bg-600 rounded p-2 text-[9px] font-mono text-gray-400">
                    <div className="text-gray-300">{text}</div>
                    {(savings != null || conf) && (
                      <div className="text-[8px] text-gray-600 mt-1 flex gap-3">
                        {savings != null && savings > 0 && <span className="text-ok">saves {savings} gates</span>}
                        {conf && <span>confidence: {conf}</span>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {!result && !loading && !error && (
        <div className="text-[9px] text-gray-600 font-mono text-center py-4">
          Analyse your circuit for gate count efficiency and possible reductions using universal gate sets.
        </div>
      )}
    </div>
  );
}
