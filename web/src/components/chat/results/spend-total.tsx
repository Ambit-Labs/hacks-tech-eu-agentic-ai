"use client";

/** `spend_total`: one borough, one period, one number. */

import type { SpendTotal } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { EmptyResult, MatchedValues, ResultCard, Stat, Stats } from "./shared";

export function SpendTotalResult({ result }: { result: SpendTotal }) {
  const title = `${fmt.borough(result.borough)} total spend`;
  const meta = fmt.period(result.period_from, result.period_to);

  if (result.payments === 0) {
    return (
      <ResultCard meta={meta} title={title}>
        <EmptyResult>No payments matched this period and filter.</EmptyResult>
        <MatchedValues matched={result.matched} />
      </ResultCard>
    );
  }

  return (
    <ResultCard meta={meta} title={title}>
      <Stats>
        <Stat label="Total" value={fmt.money(result.total_gbp)} />
        <Stat label="Payments" value={fmt.count(result.payments)} />
        <Stat label="Average payment" value={fmt.money(result.total_gbp / result.payments)} />
      </Stats>
      <MatchedValues matched={result.matched} />
    </ResultCard>
  );
}
