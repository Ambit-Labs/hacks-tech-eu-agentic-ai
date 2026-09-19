"use client";

/**
 * One component per tool result.
 *
 * `ToolResult` is the only thing the conversation renders for a tool call: it
 * picks the component by tool name, and covers the three states that are not a
 * drawing, a call still running, a call that failed, and a result whose shape
 * no longer matches `agent/tools.py`. A tool this file does not know, such as
 * the demo tools of the `ai-sdk` backend, renders nothing. To add one, mirror
 * its Pydantic model in `@/lib/agent-results`, write the component next to
 * these, and add a case to both switches below.
 */

import { getToolName } from "ai";
import { CircleAlertIcon } from "lucide-react";
import { useMemo } from "react";

import { Shimmer } from "@/components/ai-elements/shimmer";
import type { ToolPart } from "@/components/ai-elements/tool";
import {
  type AgentToolName,
  type BoroughComparison,
  type Coverage,
  isAgentToolName,
  type Payments,
  RESULT_SCHEMAS,
  type SpendBy,
  type SpendTotal,
  type SupplierPayments,
  type ToolInput,
  toolInputSchema,
} from "@/lib/agent-results";
import * as fmt from "@/lib/format";

import { BoroughComparisonResult } from "./borough-comparison";
import { CoverageResult } from "./coverage";
import { PaymentsResult } from "./payments";
import { SpendByResult } from "./spend-by";
import { SpendTotalResult } from "./spend-total";
import { SupplierPaymentsResult } from "./supplier-payments";

/** "Camden's ", or nothing when the tool was given no borough. */
function possessive(borough?: string | null): string {
  return borough ? `${fmt.borough(borough)}'s ` : "";
}

/** " in Camden", or the honest alternative when every borough is searched. */
function scope(borough?: string | null): string {
  return borough ? ` in ${fmt.borough(borough)}` : " across every borough";
}

/** What the shimmer says while a call is in flight, in the words of the question. */
const RUNNING: Record<AgentToolName, (input: ToolInput) => string> = {
  coverage: (input) =>
    input.borough
      ? `Checking which months ${fmt.borough(input.borough)} covers`
      : "Checking which boroughs and months are loaded",
  spend_total: (input) => `Adding up ${possessive(input.borough)}total spend`,
  spend_by: (input) =>
    `Adding up ${possessive(input.borough)}spend by ${(input.group_by ?? "").replace("_", " ") || "category"}`,
  supplier_payments: (input) =>
    input.supplier_like
      ? `Looking up payments to "${input.supplier_like}"`
      : "Looking up payments to a supplier",
  largest_payments: (input) => `Finding the biggest payments${scope(input.borough)}`,
  search_payments: (input) =>
    input.text ? `Searching for "${input.text}"${scope(input.borough)}` : "Searching the payments",
  compare_boroughs: (input) =>
    input.boroughs?.length ? `Comparing ${fmt.boroughs(input.boroughs)}` : "Comparing boroughs",
};

/** A validated result, or the news that the output no longer fits its schema. */
type Parsed =
  | { kind: "coverage"; data: Coverage }
  | { kind: "spend_total"; data: SpendTotal }
  | { kind: "spend_by"; data: SpendBy }
  | { kind: "supplier_payments"; data: SupplierPayments }
  | { kind: "payments"; data: Payments }
  | { kind: "compare_boroughs"; data: BoroughComparison }
  | { kind: "invalid" };

function parse(name: AgentToolName, output: unknown): Parsed {
  switch (name) {
    case "coverage": {
      const result = RESULT_SCHEMAS.coverage.safeParse(output);
      return result.success ? { kind: "coverage", data: result.data } : { kind: "invalid" };
    }
    case "spend_total": {
      const result = RESULT_SCHEMAS.spend_total.safeParse(output);
      return result.success ? { kind: "spend_total", data: result.data } : { kind: "invalid" };
    }
    case "spend_by": {
      const result = RESULT_SCHEMAS.spend_by.safeParse(output);
      return result.success ? { kind: "spend_by", data: result.data } : { kind: "invalid" };
    }
    case "supplier_payments": {
      const result = RESULT_SCHEMAS.supplier_payments.safeParse(output);
      return result.success
        ? { kind: "supplier_payments", data: result.data }
        : { kind: "invalid" };
    }
    case "largest_payments":
    case "search_payments": {
      const result = RESULT_SCHEMAS[name].safeParse(output);
      return result.success ? { kind: "payments", data: result.data } : { kind: "invalid" };
    }
    case "compare_boroughs": {
      const result = RESULT_SCHEMAS.compare_boroughs.safeParse(output);
      return result.success ? { kind: "compare_boroughs", data: result.data } : { kind: "invalid" };
    }
  }
}

function Unparseable() {
  return <p className="text-muted-foreground text-sm">Could not display this result.</p>;
}

function period(input: ToolInput): string {
  return input.period_from && input.period_to ? fmt.period(input.period_from, input.period_to) : "";
}

export function ToolResult({ part }: { part: ToolPart }) {
  const name = getToolName(part);

  if (!isAgentToolName(name)) {
    return null;
  }

  return <AgentResult name={name} part={part} />;
}

function AgentResult({ name, part }: { name: AgentToolName; part: ToolPart }) {
  const output = part.state === "output-available" ? part.output : undefined;
  // The AI SDK mutates the part in place as the answer streams, so the output
  // object keeps its identity and this validates once per call. Parsing on
  // every render would hand the charts a new array each time, and Recharts,
  // which keeps its series in a store of its own, would then re-render itself
  // into React's update-depth limit.
  const parsed = useMemo(() => (output === undefined ? null : parse(name, output)), [name, output]);

  // The input streams in as partial JSON, so it is read leniently and the
  // running line falls back to plainer words when a field is not there yet.
  const input = toolInputSchema.safeParse(part.input);
  const args: ToolInput = input.success ? input.data : {};

  if (part.state === "input-streaming" || part.state === "input-available") {
    return <Shimmer className="text-sm">{RUNNING[name](args)}</Shimmer>;
  }

  if (part.state === "output-error") {
    return (
      <p className="flex items-start gap-2 text-destructive text-sm">
        <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
        <span>{part.errorText || "That lookup failed."}</span>
      </p>
    );
  }

  if (parsed === null) {
    return null;
  }

  switch (parsed.kind) {
    case "coverage":
      return <CoverageResult result={parsed.data} />;
    case "spend_total":
      return <SpendTotalResult result={parsed.data} />;
    case "spend_by":
      return <SpendByResult result={parsed.data} />;
    case "supplier_payments":
      return <SupplierPaymentsResult result={parsed.data} />;
    case "payments":
      return (
        <PaymentsResult
          meta={period(args)}
          result={parsed.data}
          title={
            name === "largest_payments"
              ? `Biggest payments${scope(args.borough)}`
              : args.text
                ? `Payments matching "${args.text}"${scope(args.borough)}`
                : "Payments found"
          }
        />
      );
    case "compare_boroughs":
      return <BoroughComparisonResult result={parsed.data} />;
    default:
      return <Unparseable />;
  }
}
