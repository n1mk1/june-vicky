"use client";

import { useMemo } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { wikilinksToMarkdown } from "@/lib/kb";
import { cn } from "@/lib/utils";

interface MarkdownProps {
  source: string;
  /** Note id for a wikilink target, or null when no note has that name yet. */
  resolve: (target: string) => string | null;
  onOpen: (id: string) => void;
  /** A link to a note that doesn't exist yet creates it (Obsidian behaviour). */
  onCreate?: (title: string) => void;
  className?: string;
}

/** Reading view: GitHub-flavoured markdown with `[[wikilinks]]` that open the linked note. */
export function Markdown({ source, resolve, onOpen, onCreate, className }: MarkdownProps) {
  const md = useMemo(() => wikilinksToMarkdown(source), [source]);
  return (
    <div className={cn("kb-prose", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("wikilink:") ? url : defaultUrlTransform(url))}
        components={{
          a({ href, children }) {
            if (href?.startsWith("wikilink:")) {
              const target = decodeURIComponent(href.slice("wikilink:".length));
              const id = resolve(target);
              return (
                <button
                  type="button"
                  className={cn("kb-wikilink", !id && "kb-wikilink-missing")}
                  title={id ? `Open ${target}` : `${target} doesn't exist yet. Click to create it.`}
                  onClick={() => (id ? onOpen(id) : onCreate?.(target))}
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
          table({ children }) {
            return (
              <div className="kb-table-wrap scroll-thin">
                <table>{children}</table>
              </div>
            );
          },
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}
