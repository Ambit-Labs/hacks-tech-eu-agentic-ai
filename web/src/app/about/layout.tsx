import { SiteHeader } from "@/components/site-header";

// The body never scrolls (the chat manages its own), so the prose scrolls here.
export default function AboutLayout({ children }: LayoutProps<"/about">) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SiteHeader />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <article className="mx-auto max-w-2xl px-4 py-10 sm:px-6 sm:py-14">{children}</article>
      </main>
    </div>
  );
}
