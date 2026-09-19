"use client";

/**
 * The line shown while the agent works: Scrooge, a shimmering phrase and the
 * seconds so far.
 *
 * Scrooge has two poses. "checking" is him at the books, for a tool call that
 * is reading the payments. "thinking" is the expression loop, for the wait
 * before the first step and for the answer being written. The pose follows
 * `text` unless the caller names one.
 *
 * With `text` it describes one step and stays put. Without it, nothing is
 * known yet about what the agent will do, so it rotates through dry remarks
 * about bureaucracy. The remarks mock process (committees, paperwork, sign-off)
 * and never a borough, a supplier or a person: the app states facts about named
 * bodies, and a loading line must not read as a verdict on one.
 */

import { useReducedMotion } from "motion/react";
import Image from "next/image";
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

type Pose = "thinking" | "checking";

const POSE_SRC: Record<Pose, string> = {
  thinking: "/scrooge-animated.svg",
  checking: "/scrooge-checking.svg",
};

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

/** Scrooge on his own. Decorative: the text beside or above him says what is going on. */
export function Scrooge({ pose }: { pose: Pose }) {
  return (
    // unoptimized: Next's image optimiser refuses SVG unless told otherwise.
    <Image
      alt=""
      className="size-12 shrink-0"
      height={48}
      src={POSE_SRC[pose]}
      unoptimized
      width={48}
    />
  );
}

export function WorkingLine({
  text,
  pose,
  mascot = true,
}: {
  text?: string;
  pose?: Pose;
  /** False under an answer's own Scrooge, so a message never shows him twice. */
  mascot?: boolean;
}) {
  const reducedMotion = useReducedMotion() ?? false;
  // The expression loop is animated inside the file, where CSS cannot stop it,
  // so reduced motion gets the still pose whatever was asked for.
  const shown: Pose = reducedMotion ? "checking" : (pose ?? (text ? "checking" : "thinking"));
  const seconds = useElapsedSeconds();
  const index = useRotatingIndex(text === undefined && !reducedMotion);
  const phrase = `${text ?? IDLE_PHRASES[index]}…`;

  return (
    <output className="flex items-center gap-2 text-sm">
      {/* A screen reader hears the step once. The rotating remark and the
          ticking seconds would otherwise be announced again on every change. */}
      <span className="sr-only">{text ?? "Working on it"}</span>
      <span aria-hidden className="contents">
        {mascot ? <Scrooge pose={shown} /> : null}
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
