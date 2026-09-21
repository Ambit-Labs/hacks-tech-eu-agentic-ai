"use client";

/**
 * The Buy Me a Coffee button.
 *
 * Their embed snippet draws itself with `document.writeln`, which does nothing
 * once the page has parsed, and React adds scripts after that. The same script
 * also defines `window.bmcBtnWidget`, which returns the button's HTML, so we
 * load it without the `data-name` that triggers the write and call that.
 */

import Script from "next/script";
import { useState } from "react";

const BMC_SCRIPT = "https://cdnjs.buymeacoffee.com/1.0.0/button.prod.min.js";
const BMC_URL = "https://buymeacoffee.com/scrooge.fiy";

// The values from the snippet Buy Me a Coffee generated for the account.
const BMC = {
  text: "Buy me a coffee",
  slug: "scrooge.fiy",
  color: "#FFDD00",
  emoji: "",
  font: "Cookie",
  fontColor: "#000000",
  outlineColor: "#000000",
  coffeeColor: "#ffffff",
};

declare global {
  interface Window {
    bmcBtnWidget?: (
      text: string,
      slug: string,
      color: string,
      emoji: string,
      font?: string,
      fontColor?: string,
      outlineColor?: string,
      coffeeColor?: string,
    ) => string;
  }
}

export function BmcButton() {
  const [html, setHtml] = useState<string | null>(null);

  return (
    <div className="mt-6">
      <Script
        onReady={() => {
          const widget = window.bmcBtnWidget;
          if (widget) {
            setHtml(
              widget(
                BMC.text,
                BMC.slug,
                BMC.color,
                BMC.emoji,
                BMC.font,
                BMC.fontColor,
                BMC.outlineColor,
                BMC.coffeeColor,
              ),
            );
          }
        }}
        src={BMC_SCRIPT}
      />
      {html ? (
        // The markup comes from their script and our constants, no user input.
        <div dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        // Shown until the script loads, and for good if a blocker stops it.
        <a
          className="text-foreground underline underline-offset-4"
          href={BMC_URL}
          rel="noreferrer"
          target="_blank"
        >
          Buy me a coffee
        </a>
      )}
    </div>
  );
}
