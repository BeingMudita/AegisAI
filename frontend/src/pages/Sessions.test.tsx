import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "../components/ui";
import type { AgentTurn, ToolCall } from "../types";
import { decisionOf, statusTone } from "./Sessions";

function turn(partial: Partial<AgentTurn>): AgentTurn {
  return {
    id: "t1",
    session_id: "s1",
    agent: "FinanceAgent",
    message: "hi",
    answer: "ok",
    blocked: false,
    brain: "rule_based",
    trace: [],
    tool_calls: [],
    context: [],
    dropped: [],
    redactions: {},
    duration_ms: 1,
    created_at: new Date().toISOString(),
    ...partial,
  };
}

function toolCall(partial: Partial<ToolCall>): ToolCall {
  return {
    id: "c1",
    agent: "FinanceAgent",
    tool: "read_database",
    arguments: {},
    status: "EXECUTED",
    decision_reason: "",
    checks: [],
    output: null,
    output_action: null,
    redactions: {},
    requested_at: new Date().toISOString(),
    ...partial,
  };
}

describe("decisionOf", () => {
  it("is BLOCK when the turn was blocked at input", () => {
    expect(decisionOf(turn({ blocked: true }))).toBe("BLOCK");
  });
  it("is BLOCK when a tool was denied", () => {
    expect(decisionOf(turn({ tool_calls: [toolCall({ status: "DENIED" })] }))).toBe("BLOCK");
  });
  it("is BLOCK when a tool output was withheld", () => {
    expect(decisionOf(turn({ tool_calls: [toolCall({ output_action: "BLOCK" })] }))).toBe("BLOCK");
  });
  it("is CONFIRM when a trace stage was flagged but nothing blocked", () => {
    expect(
      decisionOf(turn({ trace: [{ stage: "input_firewall", status: "flagged", detail: "", data: {} }] })),
    ).toBe("CONFIRM");
  });
  it("is CONFIRM when a tool output was sanitised (FLAG)", () => {
    expect(decisionOf(turn({ tool_calls: [toolCall({ output_action: "FLAG" })] }))).toBe("CONFIRM");
  });
  it("is ALLOW for a clean turn", () => {
    expect(
      decisionOf(turn({ trace: [{ stage: "input_firewall", status: "passed", detail: "", data: {} }] })),
    ).toBe("ALLOW");
  });
});

describe("statusTone", () => {
  it("maps stopped states to critical and suspicious to warning", () => {
    expect(statusTone("blocked")).toBe("critical");
    expect(statusTone("denied")).toBe("critical");
    expect(statusTone("flagged")).toBe("warning");
    expect(statusTone("passed")).toBe("good");
    expect(statusTone("skipped")).toBe("neutral");
  });
});

describe("Badge rendering", () => {
  it("shows its label text", () => {
    render(<Badge tone="critical">BLOCK</Badge>);
    expect(screen.getByText("BLOCK")).toBeInTheDocument();
  });
});
