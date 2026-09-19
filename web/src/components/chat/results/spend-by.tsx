"use client";

/** `spend_by`: one borough's spend broken down by department, purpose, supplier, month or year. */

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { SpendBy } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { CategoryTick, EmptyResult, MatchedValues, ResultCard, Stat, Stats } from "./shared";

const CHART_CONFIG = {
  total_gbp: { label: "Total", color: "var(--chart-5)" },
} satisfies ChartConfig;

// Recharts holds its props in a store and reacts to a new object, so the
// margin is one constant rather than a fresh literal on every render.
const MARGIN = { bottom: 4, left: 4, right: 12, top: 4 };

/** What the breakdown is called, in the title and above the first column. */
const GROUP_LABELS: Record<string, string> = {
  department: "Department",
  purpose: "Purpose",
  supplier: "Supplier",
  month: "Month",
  financial_year: "Financial year",
};

/** Groups that run along time, which read as columns rather than as a ranking. */
const TIME_GROUPS = new Set(["month", "financial_year"]);

// A category tick has about 100px next to the bars. Longer labels are cut
// here rather than left to wrap onto a second line; the table under the chart
// and the tooltip both carry the whole value.
const TICK_CHARS = 13;

function tick(value: string, group: string): string {
  const label = group === "month" ? fmt.month(value) : value;
  return label.length > TICK_CHARS ? `${label.slice(0, TICK_CHARS - 1)}…` : label;
}

export function SpendByResult({ result }: { result: SpendBy }) {
  const group = result.group_by;
  const label = GROUP_LABELS[group] ?? group;
  const title = `${fmt.borough(result.borough)} spend by ${label.toLowerCase()}`;
  const meta = fmt.period(result.period_from, result.period_to);

  if (result.rows.length === 0) {
    return (
      <ResultCard meta={meta} title={title}>
        <EmptyResult>No payments matched, so there is nothing to break down.</EmptyResult>
        <MatchedValues matched={result.matched} />
      </ResultCard>
    );
  }

  const total = result.rows.reduce((sum, row) => sum + row.total_gbp, 0);
  const payments = result.rows.reduce((sum, row) => sum + row.payments, 0);
  const overTime = TIME_GROUPS.has(group);
  // One bar per row, so the chart grows with the breakdown instead of
  // squeezing twenty suppliers into a fixed height.
  const height = overTime ? 220 : Math.min(460, Math.max(140, result.rows.length * 30 + 28));

  return (
    <ResultCard meta={meta} title={title}>
      <Stats>
        <Stat
          label={
            overTime
              ? `Total, ${result.rows.length} ${label.toLowerCase()}s`
              : `Total, top ${result.rows.length}`
          }
          value={fmt.money(total)}
        />
        <Stat label="Payments" value={fmt.count(payments)} />
      </Stats>

      <ChartContainer className="aspect-auto w-full" config={CHART_CONFIG} style={{ height }}>
        <BarChart
          accessibilityLayer
          data={result.rows}
          layout={overTime ? "horizontal" : "vertical"}
          margin={MARGIN}
        >
          <CartesianGrid horizontal={overTime} vertical={!overTime} />
          {overTime ? (
            <>
              <XAxis
                axisLine={false}
                dataKey="key"
                minTickGap={8}
                tickFormatter={(value: string) => tick(value, group)}
                tickLine={false}
                tickMargin={6}
              />
              <YAxis
                axisLine={false}
                tickFormatter={fmt.moneyCompact}
                tickLine={false}
                width={56}
              />
            </>
          ) : (
            <>
              <XAxis
                axisLine={false}
                tickFormatter={fmt.moneyCompact}
                tickLine={false}
                tickMargin={6}
                type="number"
              />
              <YAxis
                axisLine={false}
                dataKey="key"
                // Every bar keeps its label. Left to itself the axis drops
                // every other one as soon as the rows get tight.
                interval={0}
                tick={<CategoryTick format={(value) => tick(value, group)} />}
                tickLine={false}
                type="category"
                width={112}
              />
            </>
          )}
          <ChartTooltip
            content={
              <ChartTooltipContent
                formatter={(value) => (
                  <span className="font-mono tabular-nums">{fmt.money(Number(value))}</span>
                )}
                hideIndicator
                labelFormatter={(value) => (group === "month" ? fmt.month(String(value)) : value)}
              />
            }
            cursor={false}
          />
          {/* Animation off: the conversation re-renders while the answer
              streams, and every re-render would replay the bars from zero. */}
          <Bar
            dataKey="total_gbp"
            fill="var(--color-total_gbp)"
            isAnimationActive={false}
            radius={3}
          />
        </BarChart>
      </ChartContainer>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{label}</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Payments</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell className="max-w-72 truncate font-medium" title={row.key}>
                {group === "month" ? fmt.month(row.key) : row.key}
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmt.money(row.total_gbp)}</TableCell>
              <TableCell className="text-right text-muted-foreground tabular-nums">
                {fmt.count(row.payments)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <MatchedValues matched={result.matched} />
    </ResultCard>
  );
}
