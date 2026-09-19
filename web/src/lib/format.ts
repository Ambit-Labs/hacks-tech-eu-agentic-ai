/**
 * How money, dates and borough slugs read in the result components.
 *
 * One module, so a total in a chart axis, in a table cell and in a headline
 * all come out of the same formatter.
 */

const MONEY = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "GBP",
  maximumFractionDigits: 0,
});

const MONEY_EXACT = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "GBP",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const MONEY_COMPACT = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "GBP",
  notation: "compact",
  maximumFractionDigits: 1,
});

const COUNT = new Intl.NumberFormat("en-GB");

// Payment dates are plain days with no time zone. Formatting them in UTC keeps
// 2023-01-25 on the 25th; local time would move it a day west of Greenwich.
const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const MONTH = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

// Words a borough name keeps lower case: barking-and-dagenham, city-of-london,
// richmond-upon-thames.
const SMALL_WORDS = new Set(["and", "of", "on", "the", "upon"]);

/** Whole pounds, for headlines and table totals. */
export function money(value: number): string {
  return MONEY.format(value);
}

/** Pounds and pence, for one payment. */
export function moneyExact(value: number): string {
  return MONEY_EXACT.format(value);
}

/** £1.2m, for chart axes and anywhere the full number does not fit. */
export function moneyCompact(value: number): string {
  return MONEY_COMPACT.format(value).replace(/[A-Z]$/, (unit) => unit.toLowerCase());
}

export function count(value: number): string {
  return COUNT.format(value);
}

/** "3,316 payments", with the singular when there is one. */
export function payments(value: number): string {
  return `${count(value)} ${value === 1 ? "payment" : "payments"}`;
}

/** An ISO day as "25 Jan 2023". Anything unparseable comes back untouched. */
export function day(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : DAY.format(date);
}

/** "Jan 2023", from either a month key ("2023-01") or a day ("2023-01-01"). */
export function month(iso: string): string {
  const date = new Date(iso.length === 7 ? `${iso}-01` : iso);
  return Number.isNaN(date.getTime()) ? iso : MONTH.format(date);
}

/** "1 Jan 2023 to 31 Dec 2023". */
export function period(from: string, to: string): string {
  return `${day(from)} to ${day(to)}`;
}

/** A borough slug as its name: tower-hamlets becomes Tower Hamlets. */
export function borough(slug: string): string {
  return slug
    .split("-")
    .map((word, index) =>
      index > 0 && SMALL_WORDS.has(word) ? word : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}

/** A list of boroughs as names: "Camden, Lambeth and Barnet". */
export function boroughs(slugs: string[]): string {
  const names = slugs.map(borough);
  if (names.length < 2) {
    return names.join("");
  }
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/**
 * A directorate and a department as one label. The agent joins them with a
 * slash and keeps the separator when one side is missing, so " / Parks" and
 * "Adults and Health / " both arrive; neither reads well with the slash left in.
 */
export function department(...parts: (string | null | undefined)[]): string {
  return parts
    .flatMap((part) => (part ?? "").split(" / "))
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" / ");
}
