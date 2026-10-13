export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(amount)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

export function formatRate(value: string | null | undefined): string {
  if (!value) return "—";
  const rate = Number(value);
  if (Number.isNaN(rate)) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

export function basisLabel(basis: string | null | undefined): string {
  if (basis === "synthetic_demo") return "Synthetic demo";
  if (basis === "approved") return "Approved inputs";
  if (basis === "mixed") return "Mixed inputs";
  return "Insufficient data";
}
