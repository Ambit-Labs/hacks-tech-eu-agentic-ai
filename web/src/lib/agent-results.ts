/**
 * What the agent's tools return, mirrored from the Pydantic models in
 * `agent/tools.py`.
 *
 * Every tool output is validated against one of these before a component
 * draws it. A result that no longer matches, because a tool changed or the
 * backend is not the agent at all, then shows one muted line instead of
 * crashing the conversation. Pydantic serialises `date` as an ISO day, so
 * every date here is a string.
 */

import { z } from "zod";

const matchedSchema = z.object({
  departments: z.array(z.string()).default([]),
  purposes: z.array(z.string()).default([]),
});

const paymentSchema = z.object({
  borough: z.string(),
  payment_date: z.string(),
  supplier: z.string(),
  directorate: z.string().nullable(),
  department: z.string().nullable(),
  purpose: z.string().nullable(),
  amount_gbp: z.number(),
  reference: z.string().nullable(),
});

const groupRowSchema = z.object({
  key: z.string(),
  total_gbp: z.number(),
  payments: z.number(),
});

const coverageSchema = z.object({
  rows: z.array(
    z.object({
      borough: z.string(),
      month: z.string(),
      payments: z.number(),
      total_gbp: z.number(),
    }),
  ),
});

const spendTotalSchema = z.object({
  borough: z.string(),
  period_from: z.string(),
  period_to: z.string(),
  total_gbp: z.number(),
  payments: z.number(),
  matched: matchedSchema,
});

const spendBySchema = z.object({
  borough: z.string(),
  period_from: z.string(),
  period_to: z.string(),
  group_by: z.string(),
  rows: z.array(groupRowSchema),
  matched: matchedSchema,
});

const paymentsSchema = z.object({
  total_gbp: z.number(),
  payments: z.number(),
  rows: z.array(paymentSchema),
});

const supplierPaymentsSchema = z.object({
  supplier_like: z.string(),
  boroughs: z.array(z.string()),
  // What each borough paid, biggest payer first. Optional because an agent
  // that predates the field still answers with the plain list above.
  by_borough: z.array(groupRowSchema).optional(),
  total_gbp: z.number(),
  payments: z.number(),
  first_date: z.string().nullable(),
  last_date: z.string().nullable(),
  rows: z.array(paymentSchema),
});

const boroughComparisonSchema = z.object({
  period_from: z.string(),
  period_to: z.string(),
  rows: z.array(
    z.object({
      borough: z.string(),
      total_gbp: z.number(),
      payments: z.number(),
      population: z.number().nullable(),
      gbp_per_resident: z.number().nullable(),
    }),
  ),
  matched: matchedSchema,
});

/** One schema per tool. The keys are the tool names the agent registers. */
export const RESULT_SCHEMAS = {
  coverage: coverageSchema,
  spend_total: spendTotalSchema,
  spend_by: spendBySchema,
  supplier_payments: supplierPaymentsSchema,
  largest_payments: paymentsSchema,
  search_payments: paymentsSchema,
  compare_boroughs: boroughComparisonSchema,
} as const;

export type AgentToolName = keyof typeof RESULT_SCHEMAS;

export function isAgentToolName(name: string): name is AgentToolName {
  return name in RESULT_SCHEMAS;
}

/**
 * The tool arguments the loading line names. They arrive token by token, so
 * every field is optional and a half-built object still parses. The model
 * sends null for an optional argument it leaves out, hence nullish.
 */
export const toolInputSchema = z.object({
  borough: z.string().nullish(),
  boroughs: z.array(z.string()).nullish(),
  group_by: z.string().nullish(),
  supplier_like: z.string().nullish(),
  text: z.string().nullish(),
  period_from: z.string().nullish(),
  period_to: z.string().nullish(),
});

export type Matched = z.infer<typeof matchedSchema>;
export type Payment = z.infer<typeof paymentSchema>;
export type Coverage = z.infer<typeof coverageSchema>;
export type SpendTotal = z.infer<typeof spendTotalSchema>;
export type SpendBy = z.infer<typeof spendBySchema>;
export type Payments = z.infer<typeof paymentsSchema>;
export type SupplierPayments = z.infer<typeof supplierPaymentsSchema>;
export type BoroughComparison = z.infer<typeof boroughComparisonSchema>;
export type ToolInput = z.infer<typeof toolInputSchema>;
