/**
 * Money and date helpers.
 *
 * Money crosses the wire as a 2dp STRING and is rendered verbatim. These
 * helpers exist only for transient in-browser arithmetic (a form's running
 * total) — the server value is always authoritative.
 */

/** Mirrors the server rule: round each line to cents, then sum. */
export function lineTotal(quantity: string, unitPrice: string): number {
  const value = Number(quantity) * Number(unitPrice);
  if (!Number.isFinite(value)) return 0;
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function sumLines(lines: { quantity: string; unit_price: string }[]): number {
  return lines.reduce((sum, l) => sum + lineTotal(l.quantity, l.unit_price), 0);
}

/** Whole days a due date is past, relative to today. 0 when not overdue. */
export function daysLate(dueDate: string): number {
  const due = new Date(`${dueDate}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.floor((today.getTime() - due.getTime()) / 86_400_000);
  return diff > 0 ? diff : 0;
}
