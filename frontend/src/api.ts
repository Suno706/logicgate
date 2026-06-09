import type {
  BuildResponse, Circuit, SimResult, Fault, ConnectionSuggestion,
  FullAnalysis, HealthResponse, OptSuggestion,
} from "./types";

/* ─── Session isolation ───────────────────────────────────────────────────
 * Each browser gets a private session-id stored in localStorage. The backend
 * scopes /api/save, /api/load, /api/circuits/list, and the user-feedback log
 * by this id so two students using the same server cannot see or overwrite
 * each other's work. Optional "room" code lets a group share the same scope.
 */

function _newSessionId(): string {
  return "s_" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}

export function getSessionId(): string {
  try {
    let s = localStorage.getItem("logicgate.session_id");
    if (!s) {
      s = _newSessionId();
      localStorage.setItem("logicgate.session_id", s);
    }
    return s;
  } catch {
    return "default";
  }
}

/** Switch to a shared "room" scope so a group sees the same circuits. */
export function setRoom(code: string): void {
  const sid = code.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
  if (sid) localStorage.setItem("logicgate.session_id", "room_" + sid);
  else     localStorage.setItem("logicgate.session_id", _newSessionId());
}

export function getRoomCode(): string | null {
  const s = getSessionId();
  return s.startsWith("room_") ? s.slice(5) : null;
}

/** Remember that this browser created the named room — it can kick others. */
export function markRoomOwned(code: string): void {
  try {
    const owned = JSON.parse(localStorage.getItem("logicgate.owned_rooms") || "[]");
    if (!owned.includes(code)) {
      owned.push(code);
      localStorage.setItem("logicgate.owned_rooms", JSON.stringify(owned));
    }
  } catch { /* localStorage unavailable */ }
}

export function isRoomOwner(code: string | null | undefined): boolean {
  if (!code) return false;
  try {
    const owned = JSON.parse(localStorage.getItem("logicgate.owned_rooms") || "[]");
    return Array.isArray(owned) && owned.includes(code.toUpperCase());
  } catch {
    return false;
  }
}

export async function kickFromRoom(code: string, target_sid: string) {
  return postJSON<{ success: boolean; kicked: boolean }>(
    `/api/rooms/${encodeURIComponent(code)}/kick`,
    { target_sid }
  );
}

function authHeaders(): Record<string, string> {
  return { "X-Session-Id": getSessionId() };
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.message || j?.error) msg = j.message ?? j.error;
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export function health() {
  return getJSON<HealthResponse>("/api/health");
}

export function buildQuestion(question: string) {
  return postJSON<BuildResponse>("/api/build/question", { question });
}

export interface AskResponse {
  success: boolean;
  status?: string;
  answer?: string;
  circuit?: Circuit;
  info?: BuildResponse["info"];
  intent?: string;
  intent_confidence?: number;
  ml_source?: "ml" | "regex" | "fallback" | "knowledge_base";
  confidence?: number;
  query_id?: string;
}

export function askQuestion(question: string, circuit?: Circuit) {
  return postJSON<AskResponse>("/api/ask", { question, circuit });
}

export interface FeedbackPayload {
  query_id: string;
  helpful?: boolean;
  corrected_intent?: string;
}

export function submitFeedback(p: FeedbackPayload) {
  return postJSON<{ status: string; updated: boolean }>("/api/feedback", p);
}

export interface LearningStats {
  total_queries: number;
  helpful: number;
  unhelpful: number;
  corrected: number;
  intents: Record<string, number>;
}

export function getLearningStats() {
  return getJSON<LearningStats>("/api/learning/stats");
}

export function retrainIntent() {
  return postJSON<{ status: string; message: string }>("/api/learning/retrain", {});
}

export function buildBoolean(expression: string, targetGates?: string[]) {
  return postJSON<BuildResponse>("/api/build/boolean", {
    expression,
    target_gates: targetGates,
  });
}

export function simulate(circuit: Circuit) {
  return postJSON<SimResult>("/simulate", circuit);
}

export function analyzeFaults(circuit: Circuit) {
  return postJSON<{ status: string; fault_count: number; faults: Fault[] }>(
    "/api/analyze/faults",
    { circuit },
  );
}

export function analyzeOptimize(circuit: Circuit) {
  return postJSON<{
    status: string;
    analysis: { suggestions: OptSuggestion[] };
    summary: { potential_savings: string };
  }>("/api/analyze/optimize", { circuit });
}

export function analyzeMinimize(circuit: Circuit, constraint?: string) {
  return postJSON<{
    status: string;
    suggestions: {
      current_gate_count: number;
      benchmark: string;
      efficiency_score: number;
      suggestions: string[];
    };
  }>("/api/analyze/minimize", { circuit, constraint });
}

export function analyzeFull(circuit: Circuit, name?: string) {
  return postJSON<FullAnalysis>("/api/analyze/full", { circuit, name });
}

export function suggestConnection(circuit: Circuit, topK = 5) {
  return postJSON<{ status: string; success: boolean; suggestions: ConnectionSuggestion[] }>(
    "/api/suggest/connection",
    { circuit, top_k: topK },
  );
}

export function saveCircuit(name: string, circuit: Circuit) {
  return postJSON<{ success: boolean; message: string }>("/save", {
    name,
    gates: circuit.gates,
    wires: circuit.wires,
  });
}

export async function loadCircuit(name: string) {
  const res = await getJSON<{ success: boolean; circuit: Circuit; name: string }>(
    `/load/${encodeURIComponent(name)}`,
  );
  return res;
}

export async function listCircuits() {
  const res = await getJSON<{ success: boolean; circuits: string[] }>("/list-circuits");
  return res.circuits ?? [];
}

export async function listAllCircuits() {
  const res = await getJSON<{ success: boolean; mine: string[]; examples: string[] }>("/list-circuits");
  return { mine: res.mine ?? [], examples: res.examples ?? [] };
}

export function deleteCircuit(name: string) {
  return fetch(`/api/delete/${encodeURIComponent(name)}`, { method: "DELETE" }).then(
    (r) => r.json(),
  );
}
