"use client";

/** `coverage`: which boroughs are loaded and which months each one covers. */

import type { Coverage } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { EmptyResult, ResultCard } from "./shared";

type Row = Coverage["rows"][number];

type BoroughCoverage = {
  borough: string;
  months: Row[];
  payments: number;
  total: number;
  busiest: number;
};

function group(rows: Row[]): BoroughCoverage[] {
  const byBorough = new Map<string, BoroughCoverage>();
  for (const row of rows) {
    let entry = byBorough.get(row.borough);
    if (!entry) {
      entry = { borough: row.borough, months: [], payments: 0, total: 0, busiest: 0 };
      byBorough.set(row.borough, entry);
    }
    entry.months.push(row);
    entry.payments += row.payments;
    entry.total += row.total_gbp;
    entry.busiest = Math.max(entry.busiest, row.total_gbp);
  }
  return [...byBorough.values()];
}

/**
 * One segment per month, shaded by that month's spend. A borough with five
 * years of data has sixty of them, which is why this is a strip and not a
 * column per month.
 */
function MonthStrip({ entry }: { entry: BoroughCoverage }) {
  return (
    <div className="flex h-4 w-full gap-px overflow-hidden rounded-xs" role="presentation">
      {entry.months.map((row) => (
        <div
          className="min-w-px flex-1 bg-(--chart-5)"
          key={row.month}
          style={{ opacity: 0.25 + 0.75 * (entry.busiest ? row.total_gbp / entry.busiest : 0) }}
          title={`${fmt.month(row.month)}: ${fmt.money(row.total_gbp)}, ${fmt.payments(row.payments)}`}
        />
      ))}
    </div>
  );
}

export function CoverageResult({ result }: { result: Coverage }) {
  const boroughs = group(result.rows);

  if (boroughs.length === 0) {
    return (
      <ResultCard title="Data loaded">
        <EmptyResult>No borough is loaded yet.</EmptyResult>
      </ResultCard>
    );
  }

  return (
    <ResultCard
      meta={`${fmt.count(boroughs.length)} ${boroughs.length === 1 ? "borough" : "boroughs"}, ${fmt.count(result.rows.length)} months`}
      title="Data loaded"
    >
      <ul className="flex flex-col gap-3">
        {boroughs.map((entry) => (
          <li className="flex flex-col gap-1" key={entry.borough}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-medium text-sm">{fmt.borough(entry.borough)}</span>
              <span className="text-muted-foreground text-xs tabular-nums">
                {fmt.money(entry.total)} · {fmt.payments(entry.payments)}
              </span>
            </div>
            <MonthStrip entry={entry} />
            <p className="text-muted-foreground text-xs">
              {fmt.month(entry.months[0].month)} to {fmt.month(entry.months.at(-1)?.month ?? "")},{" "}
              {fmt.count(entry.months.length)} months
            </p>
          </li>
        ))}
      </ul>
    </ResultCard>
  );
}
