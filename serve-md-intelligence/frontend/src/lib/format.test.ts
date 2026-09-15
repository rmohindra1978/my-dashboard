import { describe, expect, it } from "vitest";
import { fmtMetric, fmtPct, fmtUsd, scoreColor, titleize } from "./format";

describe("format helpers", () => {
  it("formats metric values by registry format", () => {
    expect(fmtMetric(12345.6, "integer")).toBe("12,346");
    expect(fmtMetric(65432, "currency")).toBe("$65,432");
    expect(fmtMetric(23.456, "percent")).toBe("23.5%");
    expect(fmtMetric(1.234, "decimal1", "per_1000")).toBe("1.2 /1k");
    expect(fmtMetric(null, "integer")).toBe("—");
  });
  it("formats currency compactly", () => {
    expect(fmtUsd(1_500_000)).toBe("$1.50M");
    expect(fmtUsd(-42_000)).toBe("-$42k");
    expect(fmtUsd(999)).toBe("$999");
  });
  it("maps scores to the red→green ramp", () => {
    expect(scoreColor(null)).toBe("#cbd5e1");
    expect(scoreColor(0)).toBe("#ea580c");
    expect(scoreColor(100)).toBe("#15803d");
  });
  it("misc", () => {
    expect(fmtPct(12.345)).toBe("12.3%");
    expect(titleize("ma_penetration_pct")).toBe("Ma Penetration Pct");
  });
});
