import { describe, expect, it } from "vitest";
import { basisLabel, formatMoney, formatRate } from "./format";

describe("dashboard formatters", () => {
  it("formats API decimal strings without inventing a value", () => {
    expect(formatMoney("3860.00")).toBe("$3,860.00");
    expect(formatMoney(null)).toBe("—");
    expect(formatRate("0.213675")).toBe("21.4%");
    expect(formatRate(null)).toBe("—");
  });

  it("labels synthetic metrics explicitly", () => {
    expect(basisLabel("synthetic_demo")).toBe("Synthetic demo");
    expect(basisLabel("insufficient_data")).toBe("Insufficient data");
  });
});
