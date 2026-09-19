"use client";

/** The pieces every result component is built from: the card, stats, badges, the payments table. */

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { Matched, Payment } from "@/lib/agent-results";
import * as fmt from "@/lib/format";
import type { ReactNode } from "react";

/** The frame around one tool result: a title, a line of context, the drawing. */
export function ResultCard({
  title,
  meta,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="not-prose w-full overflow-hidden rounded-md border bg-card text-card-foreground">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b px-3 py-2">
        <h3 className="font-medium text-sm">{title}</h3>
        {meta ? <p className="text-muted-foreground text-xs">{meta}</p> : null}
      </header>
      <div className="flex flex-col gap-3 p-3">{children}</div>
    </section>
  );
}

/** One figure with its label. */
export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="truncate font-semibold text-base tabular-nums">{value}</p>
    </div>
  );
}

export function Stats({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-x-8 gap-y-3">{children}</div>;
}

export function EmptyResult({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground text-sm">{children}</p>;
}

/**
 * A one-line label for a chart's category axis.
 *
 * Recharts wraps its own tick at the axis width, which turns a long supplier
 * into two rows that collide with the bar above. This one is cut instead, and
 * the table under every chart carries the whole value.
 */
export function CategoryTick({
  format,
  payload,
  x,
  y,
}: {
  format: (value: string) => string;
  payload?: { value?: unknown };
  x?: number | string;
  y?: number | string;
}) {
  return (
    <text className="fill-muted-foreground text-xs" dy={4} textAnchor="end" x={x} y={y}>
      {format(String(payload?.value ?? ""))}
    </text>
  );
}

/** A label that has to fit: truncated on screen, whole in the title attribute. */
export function Truncated({ className, text }: { className?: string; text: string }) {
  return (
    <span className={className} title={text}>
      {text}
    </span>
  );
}

/**
 * Which department and purpose values a substring filter matched. Every
 * borough labels these differently, so the answer is only readable next to
 * the values behind it.
 */
export function MatchedValues({ matched }: { matched: Matched }) {
  const values = [
    ...matched.departments.map((value) => ({ kind: "department", label: fmt.department(value) })),
    ...matched.purposes.map((value) => ({ kind: "purpose", label: value })),
  ].filter((value) => value.label);

  if (values.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-muted-foreground text-xs">Matched</span>
      {values.map((value) => (
        <Badge className="max-w-56" key={`${value.kind}-${value.label}`} variant="outline">
          <Truncated className="truncate" text={value.label} />
        </Badge>
      ))}
    </div>
  );
}

/** Boroughs as name badges. */
export function BoroughBadges({ slugs }: { slugs: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {slugs.map((slug) => (
        <Badge key={slug} variant="secondary">
          {fmt.borough(slug)}
        </Badge>
      ))}
    </div>
  );
}

/** "Showing 50 of 76,159 payments", when the tool counted more than it returned. */
export function ShowingRows({ shown, total }: { shown: number; total: number }) {
  if (shown >= total) {
    return null;
  }
  return (
    <p className="text-muted-foreground text-xs">
      Showing {fmt.count(shown)} of {fmt.payments(total)}.
    </p>
  );
}

/** The payment rows a tool returned. The borough column is dropped when they all share one. */
export function PaymentsTable({ rows, showBorough }: { rows: Payment[]; showBorough: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          {showBorough ? <TableHead>Borough</TableHead> : null}
          <TableHead>Supplier</TableHead>
          <TableHead>Department</TableHead>
          <TableHead>Purpose</TableHead>
          <TableHead className="text-right">Amount</TableHead>
          <TableHead>Reference</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={`${row.reference ?? row.supplier}-${row.payment_date}-${index}`}>
            <TableCell>{fmt.day(row.payment_date)}</TableCell>
            {showBorough ? <TableCell>{fmt.borough(row.borough)}</TableCell> : null}
            <TableCell className="max-w-56 truncate font-medium" title={row.supplier}>
              {row.supplier}
            </TableCell>
            <TableCell
              className="max-w-48 truncate text-muted-foreground"
              title={fmt.department(row.directorate, row.department)}
            >
              {fmt.department(row.directorate, row.department) || "—"}
            </TableCell>
            <TableCell
              className="max-w-48 truncate text-muted-foreground"
              title={row.purpose ?? ""}
            >
              {row.purpose || "—"}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {fmt.moneyExact(row.amount_gbp)}
            </TableCell>
            <TableCell className="max-w-32 truncate font-mono text-muted-foreground text-xs">
              {row.reference || "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
