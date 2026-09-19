"use client";

/**
 * The line shown while the agent works: a pulsing pound sign, a shimmering
 * phrase and the seconds so far.
 *
 * With `text` it describes one tool call and stays put. Without it, nothing is
 * known yet about what the agent will do, so it rotates through dry remarks
 * about bureaucracy. The remarks mock process (committees, paperwork, sign-off)
 * and never a borough, a supplier or a person: the app states facts about named
 * bodies, and a loading line must not read as a verdict on one.
 */

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { Shimmer } from "@/components/ai-elements/shimmer";

const IDLE_PHRASES = [
  "Forming a working group",
  "Consulting the relevant committee",
  "Commissioning a feasibility study",
  "Awaiting sign-off from Finance",
  "Launching a public consultation",
  "Checking down the back of the council sofa",
  "Rounding to the nearest million",
  "Locating the receipt",
  'Filing this under "miscellaneous"',
  "Asking the consultants, day rate applies",
  "Minuting the meeting",
  "Putting the kettle on",
  "Reading the small print",
  "Following the money",
  "Raising a purchase order",
  "Referring the matter upwards",
] as const;

const ROTATE_MS = 3500;

/** Whole seconds since the component mounted, which is when the step began. */
function useElapsedSeconds(): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return seconds;
}

/** An index into IDLE_PHRASES: random to start, then stepping on while `active`. */
function useRotatingIndex(active: boolean): number {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * IDLE_PHRASES.length));

  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = setInterval(() => {
      setIndex((current) => (current + 1) % IDLE_PHRASES.length);
    }, ROTATE_MS);
    return () => clearInterval(timer);
  }, [active]);

  return index;
}

export function WorkingLine({ text }: { text?: string }) {
  const reducedMotion = useReducedMotion() ?? false;
  const seconds = useElapsedSeconds();
  const index = useRotatingIndex(text === undefined && !reducedMotion);
  const phrase = `${text ?? IDLE_PHRASES[index]}…`;

  return (
    <output className="flex items-baseline gap-2 text-sm">
      {/* A screen reader hears the step once. The rotating remark and the
          ticking seconds would otherwise be announced again on every change. */}
      <span className="sr-only">{text ?? "Working on it"}</span>
      <span aria-hidden className="contents">
        <span className="font-semibold text-primary motion-safe:animate-pulse">£</span>
        {reducedMotion ? (
          <span className="text-muted-foreground">{phrase}</span>
        ) : (
          // The key restarts the sweep when the phrase changes length.
          <Shimmer as="span" key={phrase}>
            {phrase}
          </Shimmer>
        )}
        {seconds > 0 ? (
          <span className="text-muted-foreground text-xs tabular-nums">{seconds}s</span>
        ) : null}
      </span>
    </output>
  );
}
