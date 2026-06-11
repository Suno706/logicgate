export type PrimitiveGate =
  | "INPUT" | "OUTPUT" | "CLOCK"
  | "AND" | "OR" | "NOT" | "NAND" | "NOR" | "XOR" | "XNOR" | "BUF";

export type IndicatorGate = "LED" | "VCC" | "GND";

export type MacroGate =
  | "HA"     // half adder
  | "FA"     // full adder
  | "DFF"    // D flip-flop
  | "JKFF"   // JK flip-flop
  | "TFF"    // T flip-flop
  | "SRLATCH"// SR latch
  | "MUX2"   // 2:1 multiplexer
  | "MUX4"   // 4:1 multiplexer
  | "DEC24"  // 2-to-4 decoder
  | "DEC38"  // 3-to-8 decoder
  | "ENC42"  // 4-to-2 priority encoder
  | "CMP2"   // 2-bit equality comparator
  | "REG4";  // 4-bit register

export type GateType = PrimitiveGate | IndicatorGate | MacroGate;

export type Tool = "select" | "wire" | "hand";

export type RightTab = "props" | "smart" | "truth" | "kmap" | "bool" | "sig" | "leds" | "play";

export interface Gate {
  id: string;
  type: GateType;
  x: number;
  y: number;
  label?: string;
  value?: 0 | 1;
}

export interface Wire {
  id: string;
  from_gate: string;
  to_gate: string;
  from_pin: number;
  to_pin: number;
}

export interface Circuit {
  gates: Gate[];
  wires: Wire[];
}

export interface SimResult {
  success: boolean;
  outputs: Record<string, 0 | 1>;
  warnings?: string[];
  error?: string;
}

export interface Fault {
  gate_id?: string;
  type: string;
  message: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
}

export interface BuildResponse {
  status: string;
  success: boolean;
  circuit?: Circuit;
  info?: {
    gate_count: number;
    wire_count: number;
    target_gates?: string[] | null;
    input_vars: string[];
    outputs: string[];
    simplified?: string;
  };
  answer?: string;
  name?: string;
  timestamp?: string;
}

export interface ConnectionSuggestion {
  from_gate: string;
  from_pin: number;
  to_gate: string;
  to_pin: number;
  score: number;
  reason?: string;
  label?: string;
}

export interface OptSuggestion {
  type: string;
  description?: string;
  message?: string;
  savings?: number;
}

export interface FullAnalysis {
  status: string;
  circuit_name: string;
  analysis: {
    faults: { count: number; issues: Fault[]; severity: string };
    optimization: {
      suggestions_count: number;
      suggestions: OptSuggestion[];
      potential_savings: string;
    };
    minimization: {
      current_gates: number;
      benchmark: string;
      efficiency_score: number;
      suggestions: string[];
    };
  };
}

export interface HealthResponse {
  status: string;
  version: string;
  features: string[];
  models: Record<string, boolean>;
}

export interface PinPos {
  x: number;
  y: number;
  pin: number;
  isOutput: boolean;
}

/** Spec for a macro gate: pin labels in order. */
export interface MacroSpec {
  inputs:  string[];
  outputs: string[];
  desc:    string;
}

export const MACRO_SPECS: Record<MacroGate, MacroSpec> = {
  HA:      { inputs: ["A", "B"],                     outputs: ["S", "C"],     desc: "Half Adder" },
  FA:      { inputs: ["A", "B", "Ci"],               outputs: ["S", "Co"],    desc: "Full Adder" },
  DFF:     { inputs: ["D", "CLK"],                   outputs: ["Q", "Q̅"],     desc: "D Flip-Flop" },
  JKFF:    { inputs: ["J", "K", "CLK"],              outputs: ["Q", "Q̅"],     desc: "JK Flip-Flop" },
  TFF:     { inputs: ["T", "CLK"],                   outputs: ["Q", "Q̅"],     desc: "T Flip-Flop" },
  SRLATCH: { inputs: ["S", "R"],                     outputs: ["Q", "Q̅"],     desc: "SR Latch" },
  MUX2:    { inputs: ["A", "B", "S"],                outputs: ["Y"],          desc: "2:1 MUX" },
  MUX4:    { inputs: ["D0", "D1", "D2", "D3", "S0", "S1"],
                                                     outputs: ["Y"],          desc: "4:1 MUX" },
  DEC24:   { inputs: ["A", "B"],                     outputs: ["Y0", "Y1", "Y2", "Y3"], desc: "2:4 Decoder" },
  DEC38:   { inputs: ["A", "B", "C"],                outputs: ["Y0", "Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7"], desc: "3:8 Decoder" },
  ENC42:   { inputs: ["I0", "I1", "I2", "I3"],       outputs: ["Y0", "Y1"],   desc: "4:2 Encoder" },
  CMP2:    { inputs: ["A0", "A1", "B0", "B1"],       outputs: ["EQ"],         desc: "2-bit Comparator" },
  REG4:    { inputs: ["D0", "D1", "D2", "D3", "CLK"],
                                                     outputs: ["Q0", "Q1", "Q2", "Q3"], desc: "4-bit Register" },
};
