import { createContext, useContext, useEffect, useReducer, useCallback, useRef, type Dispatch } from "react";
import type { Circuit, Gate, GateType, Wire } from "./types";
import { collab, type RemoteOp } from "./collab";

export interface CircuitState {
  circuit: Circuit;
  selected: Set<string>;
  simOutputs: Record<string, 0 | 1>;
  history: Circuit[];
  future: Circuit[];
}

type Action =
  | { type: "SET_CIRCUIT"; circuit: Circuit }
  | { type: "ADD_GATE"; gate: Gate }
  | { type: "MOVE_GATE"; id: string; x: number; y: number }
  | { type: "MOVE_SELECTED"; dx: number; dy: number }
  | { type: "REMOVE_SELECTED" }
  | { type: "ADD_WIRE"; wire: Wire }
  | { type: "REMOVE_WIRE"; id: string }
  | { type: "SET_GATE_VALUE"; id: string; value: 0 | 1 }
  | { type: "RENAME_GATE"; id: string; label: string }
  | { type: "SELECT"; ids: string[]; add?: boolean }
  | { type: "SELECT_ALL" }
  | { type: "CLEAR_SELECTION" }
  | { type: "SET_SIM_OUTPUTS"; outputs: Record<string, 0 | 1> }
  | { type: "CLEAR_SIM_OUTPUTS" }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "CLEAR" };

const MAX_HISTORY = 50;

function snapshot(state: CircuitState): CircuitState {
  const hist = [
    ...state.history,
    { gates: [...state.circuit.gates], wires: [...state.circuit.wires] },
  ].slice(-MAX_HISTORY);
  return { ...state, history: hist, future: [] };
}

function reducer(state: CircuitState, action: Action): CircuitState {
  switch (action.type) {
    case "SET_CIRCUIT":
      return {
        ...snapshot(state),
        circuit: action.circuit,
        selected: new Set(),
        simOutputs: {},
      };

    case "ADD_GATE": {
      const s = snapshot(state);
      let gate = action.gate;

      // Auto-name INPUT / OUTPUT / CLOCK by position-among-its-kind so K-Map
      // and Boolean panels read cleanly ("A=0, B=1, C=1") instead of by
      // arbitrary gate ids. The user can rename via the Props panel.
      if (!gate.label) {
        if (gate.type === "INPUT" || gate.type === "CLOCK") {
          const n = s.circuit.gates.filter((g) => g.type === "INPUT" || g.type === "CLOCK").length;
          gate = { ...gate, label: n < 26 ? String.fromCharCode(65 + n) : `IN${n}` };
        } else if (gate.type === "OUTPUT" || gate.type === "LED") {
          const n = s.circuit.gates.filter((g) => g.type === "OUTPUT" || g.type === "LED").length;
          gate = { ...gate, label: n === 0 ? "Y" : `Y${n}` };
        }
      }

      return {
        ...s,
        circuit: { ...s.circuit, gates: [...s.circuit.gates, gate] },
        selected: new Set([gate.id]),
        simOutputs: {},
      };
    }

    case "MOVE_GATE": {
      const updated = state.circuit.gates.map((g) =>
        g.id === action.id ? { ...g, x: action.x, y: action.y } : g,
      );
      return {
        ...state,
        circuit: { ...state.circuit, gates: updated },
        simOutputs: {},
      };
    }

    case "MOVE_SELECTED": {
      if (!state.selected.size) return state;
      const updated = state.circuit.gates.map((g) =>
        state.selected.has(g.id)
          ? { ...g, x: g.x + action.dx, y: g.y + action.dy }
          : g,
      );
      return {
        ...state,
        circuit: { ...state.circuit, gates: updated },
        simOutputs: {},
      };
    }

    case "REMOVE_SELECTED": {
      if (!state.selected.size) return state;
      const s = snapshot(state);
      const gates = s.circuit.gates.filter((g) => !state.selected.has(g.id));
      const wires = s.circuit.wires.filter(
        (w) => !state.selected.has(w.from_gate) && !state.selected.has(w.to_gate),
      );
      return {
        ...s,
        circuit: { gates, wires },
        selected: new Set(),
        simOutputs: {},
      };
    }

    case "ADD_WIRE": {
      const s = snapshot(state);
      const exists = s.circuit.wires.find(
        (w) =>
          w.from_gate === action.wire.from_gate &&
          w.from_pin === action.wire.from_pin &&
          w.to_gate === action.wire.to_gate &&
          w.to_pin === action.wire.to_pin,
      );
      if (exists) return state;
      return {
        ...s,
        circuit: { ...s.circuit, wires: [...s.circuit.wires, action.wire] },
        simOutputs: {},
      };
    }

    case "REMOVE_WIRE": {
      const s = snapshot(state);
      return {
        ...s,
        circuit: {
          ...s.circuit,
          wires: s.circuit.wires.filter((w) => w.id !== action.id),
        },
        simOutputs: {},
      };
    }

    case "SET_GATE_VALUE": {
      const updated = state.circuit.gates.map((g) =>
        g.id === action.id ? { ...g, value: action.value } : g,
      );
      return { ...state, circuit: { ...state.circuit, gates: updated }, simOutputs: {} };
    }

    case "RENAME_GATE": {
      const updated = state.circuit.gates.map((g) =>
        g.id === action.id ? { ...g, label: action.label } : g,
      );
      return { ...state, circuit: { ...state.circuit, gates: updated } };
    }

    case "SELECT":
      if (action.add) {
        const next = new Set(state.selected);
        action.ids.forEach((id) => next.add(id));
        return { ...state, selected: next };
      }
      return { ...state, selected: new Set(action.ids) };

    case "SELECT_ALL":
      return { ...state, selected: new Set(state.circuit.gates.map((g) => g.id)) };

    case "CLEAR_SELECTION":
      return { ...state, selected: new Set() };

    case "SET_SIM_OUTPUTS":
      return { ...state, simOutputs: action.outputs };

    case "CLEAR_SIM_OUTPUTS":
      return { ...state, simOutputs: {} };

    case "UNDO": {
      if (!state.history.length) return state;
      const history = [...state.history];
      const prev = history.pop()!;
      return {
        ...state,
        circuit: prev,
        history,
        future: [state.circuit, ...state.future],
        selected: new Set(),
        simOutputs: {},
      };
    }

    case "REDO": {
      if (!state.future.length) return state;
      const [next, ...future] = state.future;
      return {
        ...state,
        circuit: next,
        future,
        history: [...state.history, state.circuit],
        selected: new Set(),
        simOutputs: {},
      };
    }

    case "CLEAR":
      return {
        ...snapshot(state),
        circuit: { gates: [], wires: [] },
        selected: new Set(),
        simOutputs: {},
      };

    default:
      return state;
  }
}

const initialState: CircuitState = {
  circuit: { gates: [], wires: [] },
  selected: new Set(),
  simOutputs: {},
  history: [],
  future: [],
};

let gateCounter = 0;
export function nextId(prefix = "g") {
  return `${prefix}${++gateCounter}`;
}

export function makeGate(type: GateType, x: number, y: number): Gate {
  // Labels for INPUT/OUTPUT/CLOCK are assigned by the ADD_GATE reducer based
  // on how many of that kind already exist — that way they read cleanly as
  // A, B, C / Y, Y1, Y2 in K-Map and Boolean panels.
  return { id: nextId(type.slice(0, 2).toLowerCase()), type, x, y, value: 0 };
}

// Context ----------------------------------------------------------------

const StateCtx = createContext<CircuitState>(initialState);
const DispatchCtx = createContext<Dispatch<Action>>(() => {});

export { StateCtx, DispatchCtx };

export function useCircuitState() {
  return useContext(StateCtx);
}

export function useCircuitDispatch() {
  return useContext(DispatchCtx);
}

/**
 * Wraps useReducer with a side-effecting dispatch that:
 *   1. Runs the reducer locally (immediate UI update)
 *   2. Broadcasts the action to peers via WebSocket
 *
 * Remote ops (from peers) are also fed into the reducer, but the broadcast
 * is suppressed via collab.suppress so they don't echo back.
 */
export function useCircuitReducer(): [CircuitState, Dispatch<Action>] {
  const [state, baseDispatch] = useReducer(reducer, initialState);
  const dispatchRef = useRef(baseDispatch);
  dispatchRef.current = baseDispatch;
  // Track the previous circuit so we can broadcast set_circuit when a peer-
  // affecting action that doesn't map cleanly to a single op was dispatched.
  const pendingFullSync = useRef(false);

  const dispatch: Dispatch<Action> = useCallback((action) => {
    baseDispatch(action);
    const op = _actionToRemoteOp(action);
    if (op) {
      collab.broadcast(op);
    } else if (_isPeerAffecting(action)) {
      // Complex action (REMOVE_SELECTED, MOVE_SELECTED, RENAME_GATE etc.) —
      // can't be expressed as a single op without knowing state. Mark pending
      // and the effect below will broadcast the resulting circuit.
      pendingFullSync.current = true;
    }
  }, []);

  // After a complex action lands in state, broadcast the new circuit so peers
  // converge. Avoids selection-state divergence problems.
  useEffect(() => {
    if (pendingFullSync.current) {
      pendingFullSync.current = false;
      collab.broadcast({ kind: "set_circuit", payload: { circuit: state.circuit } });
    }
  }, [state.circuit]);

  // Listen for remote ops and apply them locally (without rebroadcasting).
  useEffect(() => {
    const off = collab.onRemote((op) => {
      const a = _remoteOpToAction(op);
      if (a) dispatchRef.current(a);
    });
    return off;
  }, []);

  return [state, dispatch];
}

function _isPeerAffecting(a: Action): boolean {
  return (
    a.type === "REMOVE_SELECTED" ||
    a.type === "MOVE_SELECTED" ||
    a.type === "RENAME_GATE"
  );
}

function _actionToRemoteOp(a: Action): RemoteOp | null {
  switch (a.type) {
    case "ADD_GATE":        return { kind: "add_gate",       payload: { gate: a.gate } };
    case "MOVE_GATE":       return { kind: "move_gate",      payload: { id: a.id, x: a.x, y: a.y } };
    case "ADD_WIRE":        return { kind: "add_wire",       payload: { wire: a.wire } };
    case "REMOVE_WIRE":     return { kind: "remove_wire",    payload: { id: a.id } };
    case "SET_GATE_VALUE":  return { kind: "set_gate_value", payload: { id: a.id, value: a.value } };
    case "SET_CIRCUIT":     return { kind: "set_circuit",    payload: { circuit: a.circuit } };
    case "CLEAR":           return { kind: "clear_circuit",  payload: {} };
    // REMOVE_SELECTED, RENAME_GATE, MOVE_SELECTED need special handling — for
    // now skip them (peers' selection state isn't shared), so deletions / renames
    // don't propagate. To be added in a follow-up.
    default: return null;
  }
}

function _remoteOpToAction(op: RemoteOp & { from: string }): Action | null {
  switch (op.kind) {
    case "add_gate":        return { type: "ADD_GATE",       gate: op.payload.gate };
    case "move_gate":       return { type: "MOVE_GATE",      id: op.payload.id, x: op.payload.x, y: op.payload.y };
    case "add_wire":        return { type: "ADD_WIRE",       wire: op.payload.wire };
    case "remove_wire":     return { type: "REMOVE_WIRE",    id: op.payload.id };
    case "set_gate_value":  return { type: "SET_GATE_VALUE", id: op.payload.id, value: op.payload.value };
    case "set_circuit":     return { type: "SET_CIRCUIT",    circuit: op.payload.circuit };
    case "clear_circuit":   return { type: "CLEAR" };
    case "remove_gate":     return null; // peer deletion not yet supported (see above)
    case "cursor":          return null; // handled separately by PresenceLayer
    default: return null;
  }
}

export function useCircuitActions(dispatch: Dispatch<Action>) {
  return {
    setCircuit: useCallback(
      (circuit: Circuit) => dispatch({ type: "SET_CIRCUIT", circuit }),
      [dispatch],
    ),
    addGate: useCallback(
      (gate: Gate) => dispatch({ type: "ADD_GATE", gate }),
      [dispatch],
    ),
    moveGate: useCallback(
      (id: string, x: number, y: number) => dispatch({ type: "MOVE_GATE", id, x, y }),
      [dispatch],
    ),
    removeSelected: useCallback(
      () => dispatch({ type: "REMOVE_SELECTED" }),
      [dispatch],
    ),
    addWire: useCallback(
      (wire: Wire) => dispatch({ type: "ADD_WIRE", wire }),
      [dispatch],
    ),
    removeWire: useCallback(
      (id: string) => dispatch({ type: "REMOVE_WIRE", id }),
      [dispatch],
    ),
    setGateValue: useCallback(
      (id: string, value: 0 | 1) => dispatch({ type: "SET_GATE_VALUE", id, value }),
      [dispatch],
    ),
    renameGate: useCallback(
      (id: string, label: string) => dispatch({ type: "RENAME_GATE", id, label }),
      [dispatch],
    ),
    select: useCallback(
      (ids: string[], add?: boolean) => dispatch({ type: "SELECT", ids, add }),
      [dispatch],
    ),
    selectAll: useCallback(() => dispatch({ type: "SELECT_ALL" }), [dispatch]),
    clearSelection: useCallback(() => dispatch({ type: "CLEAR_SELECTION" }), [dispatch]),
    setSimOutputs: useCallback(
      (outputs: Record<string, 0 | 1>) =>
        dispatch({ type: "SET_SIM_OUTPUTS", outputs }),
      [dispatch],
    ),
    clearSimOutputs: useCallback(
      () => dispatch({ type: "CLEAR_SIM_OUTPUTS" }),
      [dispatch],
    ),
    undo: useCallback(() => dispatch({ type: "UNDO" }), [dispatch]),
    redo: useCallback(() => dispatch({ type: "REDO" }), [dispatch]),
    clear: useCallback(() => dispatch({ type: "CLEAR" }), [dispatch]),
  };
}
