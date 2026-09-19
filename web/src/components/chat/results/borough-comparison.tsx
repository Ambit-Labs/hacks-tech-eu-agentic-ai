"use client";

/** `compare_boroughs`: several boroughs over the same period, side by side. */

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
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
import type { BoroughComparison } from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { CategoryTick, EmptyResult, MatchedValues, ResultCard } from "./shared";

const CHART_CONFIG = {
  total_gbp: { label: "Total", color: "var(--chart-5)" },
  gbp_per_resident: { label: "Per resident", color: "var(--chart-3)" },
} satisfies ChartConfig;

// Recharts holds its props in a store and reacts to a new object, so the
// margin is one constant rather than a fresh literal on every render.
const MARGIN = { bottom: 4, left: 4, right: 12, top: 4 };

type Measure = "total_gbp" | "gbp_per_resident";

export function BoroughComparisonResult({ result }: { result: BoroughComparison }) {
  const [measure, setMeasure] = useState<Measure>("total_gbp");
  const meta = fmt.period(result.period_from, result.period_to);
  const title = `Spend compared, ${result.rows.length} boroughs`;

  if (result.rows.length === 0) {
    return (
      <ResultCard meta={meta} title={title}>
        <EmptyResult>No boroughs to compare.</EmptyResult>
      </ResultCard>
    );
  }

  // Per resident needs a population, which is missing for some boroughs. The
  // toggle only appears when at least one row can answer it.
  const withPopulation = result.rows.filter((row) => row.gbp_per_resident !== null);
  const canCompareResidents = withPopulation.length > 0;
  const shown = measure === "total_gbp" ? result.rows : withPopulation;
  const money = measure === "total_gbp" ? fmt.money : fmt.moneyExact;

  return (
    <ResultCard meta={meta} title={title}>
      {canCompareResidents ? (
        <ButtonGroup>
          <Button
            aria-pressed={measure === "total_gbp"}
            onClick={() => setMeasure("total_gbp")}
            size="sm"
            variant={measure === "total_gbp" ? "secondary" : "outline"}
          >
            Total
          </Button>
          <Button
            aria-pressed={measure === "gbp_per_resident"}
            onClick={() => setMeasure("gbp_per_resident")}
            size="sm"
            variant={measure === "gbp_per_resident" ? "secondary" : "outline"}
          >
            Per resident
          </Button>
        </ButtonGroup>
      ) : null}

      <ChartContainer
        className="aspect-auto w-full"
        config={CHART_CONFIG}
        style={{ height: Math.max(120, shown.length * 34 + 28) }}
      >
        <BarChart accessibilityLayer data={shown} layout="vertical" margin={MARGIN}>
          <CartesianGrid horizontal={false} />
          <XAxis
            axisLine={false}
            tickFormatter={measure === "total_gbp" ? fmt.moneyCompact : fmt.money}
            tickLine={false}
            tickMargin={6}
            type="number"
          />
          <YAxis
            axisLine={false}
            dataKey="borough"
            interval={0}
            tick={<CategoryTick format={fmt.borough} />}
            tickLine={false}
            type="category"
            width={112}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                formatter={(value) => (
                  <span className="font-mono tabular-nums">{money(Number(value))}</span>
                )}
                hideIndicator
                labelFormatter={(value) => fmt.borough(String(value))}
              />
            }
            cursor={false}
          />
          {/* Animation off: the conversation re-renders while the answer
              streams, and every re-render would replay the bars from zero. */}
          <Bar
            dataKey={measure}
            fill={`var(--color-${measure})`}
            isAnimationActive={false}
            radius={3}
          />
        </BarChart>
      </ChartContainer>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Borough</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Payments</TableHead>
            <TableHead className="text-right">Population</TableHead>
            <TableHead className="text-right">Per resident</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.rows.map((row) => (
            <TableRow key={row.borough}>
              <TableCell className="font-medium">{fmt.borough(row.borough)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt.money(row.total_gbp)}</TableCell>
              <TableCell className="text-right text-muted-foreground tabular-nums">
                {fmt.count(row.payments)}
              </TableCell>
              <TableCell className="text-right text-muted-foreground tabular-nums">
                {row.population === null ? "—" : fmt.count(row.population)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.gbp_per_resident === null ? "—" : fmt.moneyExact(row.gbp_per_resident)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <MatchedValues matched={result.matched} />
    </ResultCard>
  );
}
