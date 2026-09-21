import type { MDXComponents } from "mdx/types";
import type { ComponentPropsWithoutRef } from "react";

// There is no typography plugin in this project, so prose gets its look here.
const components: MDXComponents = {
  h1: ({ children, ...props }: ComponentPropsWithoutRef<"h1">) => (
    <h1 className="font-semibold text-3xl tracking-tight" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: ComponentPropsWithoutRef<"h2">) => (
    <h2 className="mt-10 font-semibold text-xl tracking-tight" {...props}>
      {children}
    </h2>
  ),
  p: (props: ComponentPropsWithoutRef<"p">) => (
    <p className="mt-4 text-muted-foreground leading-7" {...props} />
  ),
  ul: (props: ComponentPropsWithoutRef<"ul">) => (
    <ul className="mt-4 list-disc space-y-2 pl-5 text-muted-foreground leading-7" {...props} />
  ),
  strong: (props: ComponentPropsWithoutRef<"strong">) => (
    <strong className="font-medium text-foreground" {...props} />
  ),
  a: ({ children, ...props }: ComponentPropsWithoutRef<"a">) => (
    <a className="text-foreground underline underline-offset-4" {...props}>
      {children}
    </a>
  ),
};

export function useMDXComponents(): MDXComponents {
  return components;
}
