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

/**
 * Stable device identifier — generated once per browser, kept across
 * reloads and tab restarts. Used by the realtime layer for room bans
 * that survive a refresh. We DON'T derive this from session_id because
 * session_id can change when the user joins/leaves a room. The device
 * id is purely an identity token: not tied to permissions, not used
 * for circuit ownership.
 *
 * Storing in localStorage means clearing browser data resets it — that's
 * acceptable; a kicked user determined to come back can always start
 * over from a clean browser, same as any web ban.
 */
const DEVICE_KEY = "logicgate.device_id";
export function getDeviceId(): string {
  try {
    let d = localStorage.getItem(DEVICE_KEY);
    if (!d) {
      d = "d_" + Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
      localStorage.setItem(DEVICE_KEY, d);
    }
    return d;
  } catch {
    // Private mode / disabled storage — fall back to a per-page id so
    // collab still works, just won't survive a refresh.
    return "d_ephemeral_" + Math.random().toString(36).slice(2, 12);
  }
}

/**
 * Session-id resolution order (per-tab → per-browser):
 *   1. URL ?room=XYZ           — current tab is in room XYZ
 *   2. sessionStorage room    — this tab's room (survives reloads, not tabs)
 *   3. localStorage room      — legacy / fallback
 *   4. fresh guest id
 *
 * Using sessionStorage instead of localStorage for the room means two
 * browser TABS can be in different rooms simultaneously — required for
 * one user hosting + watching multiple rooms.
 */
export function getSessionId(): string {
  try {
    // 1. URL takes precedence — but ONLY when the URL has ?room=XYZ.
    const url = new URL(window.location.href);
    const fromUrl = (url.searchParams.get("room") || "").trim();
    if (fromUrl) {
      const sid = "room_" + fromUrl.toLowerCase().replace(/[^a-z0-9_-]/g, "");
      // Cache in sessionStorage so subsequent navigations on this tab stay
      // in the same room even if the user removes ?room= from the URL bar.
      sessionStorage.setItem("logicgate.session_id", sid);
      return sid;
    }
    // 2. Per-tab room
    let s = sessionStorage.getItem("logicgate.session_id");
    if (s) return s;
    // 3. Per-browser fallback (legacy)
    s = localStorage.getItem("logicgate.session_id");
    if (!s) {
      // 4. Fresh guest id
      s = _newSessionId();
      localStorage.setItem("logicgate.session_id", s);
    }
    return s;
  } catch {
    return "default";
  }
}

/** Switch to a shared "room" scope. Stored PER-TAB (sessionStorage) so two
 * tabs of the same browser can host/watch different rooms. */
export function setRoom(code: string): void {
  try {
    const sid = code.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    if (sid) {
      sessionStorage.setItem("logicgate.session_id", "room_" + sid);
    } else {
      sessionStorage.removeItem("logicgate.session_id");
      localStorage.setItem("logicgate.session_id", _newSessionId());
    }
  } catch { /* */ }
}

export function getRoomCode(): string | null {
  const s = getSessionId();
  return s.startsWith("room_") ? s.slice(5).toUpperCase() : null;
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

/** Store the owner_token returned by /api/rooms/new. Sent on later
 * owner-only calls so the server keeps recognizing us as host even after
 * setRoom() rewrites session_id to "room_<code>". */
export function saveOwnerToken(code: string, token: string): void {
  try {
    const obj = JSON.parse(localStorage.getItem("logicgate.owner_tokens") || "{}");
    obj[code.toUpperCase()] = token;
    localStorage.setItem("logicgate.owner_tokens", JSON.stringify(obj));
  } catch { /* */ }
}
export function getOwnerToken(code: string | null | undefined): string | null {
  if (!code) return null;
  try {
    const obj = JSON.parse(localStorage.getItem("logicgate.owner_tokens") || "{}");
    return obj[code.toUpperCase()] || null;
  } catch {
    return null;
  }
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

/** Server-trusted owner check — accepts either matching session_id OR a
 * stored owner_token (covers guests after setRoom() rewrites session_id). */
export async function fetchRoomInfo(code: string): Promise<{
  exists: boolean;
  is_owner: boolean;
  max_users?: number;
}> {
  const tok = getOwnerToken(code);
  const res = await fetch(`/api/rooms/${encodeURIComponent(code)}`, {
    headers: {
      "X-Session-Id": getSessionId(),
      ...(tok ? { "X-Owner-Token": tok } : {}),
    },
  });
  if (!res.ok) return { exists: false, is_owner: false };
  const d = await res.json();
  return {
    exists: !!d?.exists,
    is_owner: !!d?.is_owner,
    max_users: d?.max_users,
  };
}

export async function kickFromRoom(code: string, target_sid: string) {
  const tok = getOwnerToken(code);
  const res = await fetch(`/api/rooms/${encodeURIComponent(code)}/kick`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Id": getSessionId(),
      ...(tok ? { "X-Owner-Token": tok } : {}),
    },
    body: JSON.stringify({ target_sid }),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.message || j?.error) msg = j.message ?? j.error;
    } catch { /* */ }
    throw new Error(msg);
  }
  return res.json() as Promise<{ success: boolean; kicked: boolean }>;
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
