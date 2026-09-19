"use client";

/** `supplier_payments`: everything paid to suppliers whose name contains a piece of text. */

import type { SupplierPayments } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import {
  BoroughBadges,
  EmptyResult,
  PaymentsTable,
  ResultCard,
  ShowingRows,
  Stat,
  Stats,
} from "./shared";

export function SupplierPaymentsResult({ result }: { result: SupplierPayments }) {
  // The result carries no period; the dates below are the first and last
  // payment inside the one the tool was asked for.
  const title = `Paid to "${result.supplier_like}"`;

  if (result.payments === 0) {
    return (
      <ResultCard title={title}>
        <EmptyResult>
          No supplier whose name contains that text was paid in this period.
        </EmptyResult>
      </ResultCard>
    );
  }

  return (
    <ResultCard
      meta={
        result.first_date && result.last_date
          ? `${fmt.day(result.first_date)} to ${fmt.day(result.last_date)}`
          : undefined
      }
      title={title}
    >
      <Stats>
        <Stat label="Total" value={fmt.money(result.total_gbp)} />
        <Stat label="Payments" value={fmt.count(result.payments)} />
        <Stat label="Boroughs" value={fmt.count(result.boroughs.length)} />
      </Stats>
      {result.by_borough?.length ? (
        <ul className="flex flex-wrap gap-x-5 gap-y-1">
          {result.by_borough.map((row) => (
            <li className="text-sm" key={row.key}>
              <span className="font-medium">{fmt.borough(row.key)}</span>{" "}
              <span className="text-muted-foreground tabular-nums">{fmt.money(row.total_gbp)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <BoroughBadges slugs={result.boroughs} />
      )}
      <ShowingRows shown={result.rows.length} total={result.payments} />
      <PaymentsTable rows={result.rows} showBorough={result.boroughs.length > 1} />
    </ResultCard>
  );
}
