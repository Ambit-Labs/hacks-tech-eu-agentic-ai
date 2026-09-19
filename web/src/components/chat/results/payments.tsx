"use client";

/** `largest_payments` and `search_payments`: a filtered set of payments, and the rows behind it. */

import type { Payments } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { EmptyResult, PaymentsTable, ResultCard, ShowingRows, Stat, Stats } from "./shared";

export function PaymentsResult({
  result,
  title,
  meta,
}: {
  result: Payments;
  title: string;
  meta: string;
}) {
  if (result.rows.length === 0) {
    return (
      <ResultCard meta={meta} title={title}>
        <EmptyResult>No payments matched.</EmptyResult>
      </ResultCard>
    );
  }

  // Several boroughs only when the tool was not given one, and then the column
  // earns its width.
  const boroughs = new Set(result.rows.map((row) => row.borough));
  const biggest = Math.max(...result.rows.map((row) => row.amount_gbp));

  return (
    <ResultCard meta={meta} title={title}>
      <Stats>
        {/* The totals cover every payment that matched, not only the rows. */}
        <Stat label="Total matched" value={fmt.money(result.total_gbp)} />
        <Stat label="Payments matched" value={fmt.count(result.payments)} />
        <Stat label="Biggest row here" value={fmt.money(biggest)} />
      </Stats>
      <ShowingRows shown={result.rows.length} total={result.payments} />
      <PaymentsTable rows={result.rows} showBorough={boroughs.size > 1} />
    </ResultCard>
  );
}
