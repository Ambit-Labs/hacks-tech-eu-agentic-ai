import { tool } from "ai";
import { z } from "zod";

import { calculateExpression } from "@/lib/calculate";

const MAX_DICE = 20;
const MAX_SIDES = 1000;

const getCurrentTime = tool({
  description:
    "Get the current date and time in an IANA time zone, for example Europe/Bucharest or America/New_York.",
  inputSchema: z.object({
    timeZone: z
      .string()
      .describe('IANA time zone name, such as "Europe/Bucharest". Use "UTC" if unsure.'),
  }),
  execute: ({ timeZone }) => {
    const now = new Date();

    let formatter: Intl.DateTimeFormat;
    try {
      formatter = new Intl.DateTimeFormat("en-GB", {
        dateStyle: "full",
        timeStyle: "long",
        timeZone,
      });
    } catch {
      return {
        error: `"${timeZone}" is not a known IANA time zone.`,
      };
    }

    return {
      timeZone,
      localTime: formatter.format(now),
      utcTime: now.toISOString(),
    };
  },
});

const calculate = tool({
  description:
    "Evaluate an arithmetic expression. Supports + - * / % ^ and parentheses. Use it for every calculation instead of doing the arithmetic yourself.",
  inputSchema: z.object({
    expression: z.string().describe('The expression to evaluate, such as "17 * 23 + 4".'),
  }),
  execute: ({ expression }) => {
    try {
      return { expression, result: calculateExpression(expression) };
    } catch (error) {
      return {
        expression,
        error: error instanceof Error ? error.message : "Could not evaluate the expression.",
      };
    }
  },
});

const rollDice = tool({
  description: "Roll one or more dice and return each roll plus the total.",
  inputSchema: z.object({
    count: z.int().min(1).max(MAX_DICE).default(1).describe("How many dice to roll."),
    sides: z.int().min(2).max(MAX_SIDES).default(6).describe("How many sides each die has."),
  }),
  execute: ({ count, sides }) => {
    const rolls = Array.from({ length: count }, () => 1 + Math.floor(Math.random() * sides));

    return {
      rolls,
      sides,
      total: rolls.reduce((sum, roll) => sum + roll, 0),
    };
  },
});

export const chatTools = { calculate, getCurrentTime, rollDice };
