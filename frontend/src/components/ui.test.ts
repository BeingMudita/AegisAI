import { describe, expect, it } from "vitest";

import { actionTone, formatBytes, formatNumber, riskTone, severityTone, trustTone } from "./ui";

describe("actionTone", () => {
  it("maps allow/execute states to good", () => {
    expect(actionTone("ALLOW")).toBe("good");
    expect(actionTone("EXECUTED")).toBe("good");
    expect(actionTone("passed")).toBe("good");
    expect(actionTone("APPROVED")).toBe("good");
  });
  it("keeps red for blocked or denied, not for a cancelled job", () => {
    expect(actionTone("BLOCK")).toBe("critical");
    expect(actionTone("DENIED")).toBe("critical");
    expect(actionTone("CANCELLED")).toBe("neutral");
  });
  it("maps the FLAG (confirm) states to warning", () => {
    expect(actionTone("FLAG")).toBe("warning");
    expect(actionTone("flagged")).toBe("warning");
    expect(actionTone("redacted")).toBe("warning");
  });
  it("maps block/deny states to critical", () => {
    expect(actionTone("BLOCK")).toBe("critical");
    expect(actionTone("DENIED")).toBe("critical");
    expect(actionTone("blocked")).toBe("critical");
  });
  it("falls back to neutral for unknown states", () => {
    expect(actionTone("whatever")).toBe("neutral");
  });
});

describe("severityTone", () => {
  it("escalates with severity", () => {
    expect(severityTone("CRITICAL")).toBe("critical");
    expect(severityTone("HIGH")).toBe("serious");
    expect(severityTone("MEDIUM")).toBe("warning");
    expect(severityTone("LOW")).toBe("neutral");
    expect(severityTone("INFO")).toBe("neutral");
  });
});

describe("trustTone", () => {
  it("rewards high trust and warns on low; red stays for blocked content", () => {
    expect(trustTone("VERIFIED")).toBe("good");
    expect(trustTone("HIGH")).toBe("good");
    expect(trustTone("MEDIUM")).toBe("warning");
    expect(trustTone("LOW")).toBe("serious");
    expect(trustTone("UNTRUSTED")).toBe("serious");
  });
});

describe("riskTone", () => {
  it("escalates with tool risk", () => {
    expect(riskTone("LOW")).toBe("neutral");
    expect(riskTone("CRITICAL")).toBe("critical");
  });
});

describe("formatBytes", () => {
  it("formats sizes across units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
  });
});

describe("formatNumber", () => {
  it("adds thousands separators", () => {
    expect(formatNumber(1234567)).toBe((1234567).toLocaleString());
  });
});
