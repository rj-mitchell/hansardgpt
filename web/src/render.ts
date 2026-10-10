import DOMPurify from "dompurify";
import { marked } from "marked";
import type { Segment } from "./types";

marked.setOptions({ gfm: true, breaks: false });

const CITE = (nums: number[]) => `⁣⟦S:${nums.join(",")}⟧⁣`;
const U_OPEN = "⁣⟦U⟧⁣";
const U_CLOSE = "⁣⟦/U⟧⁣";
const L_OPEN = "⁣⟦L⟧⁣";
const L_CLOSE = "⁣⟦/L⟧⁣";

/** Mark judgemental words the server flagged in the briefing's own voice (offsets into the segment text). */
function markLoaded(s: Segment): string {
  let text = s.text;
  for (const f of [...(s.loaded ?? [])].sort((a, b) => b.start - a.start)) {
    text = text.slice(0, f.start) + L_OPEN + text.slice(f.start, f.end) + L_CLOSE + text.slice(f.end);
  }
  return text;
}

/** Markdown for a verified answer, with placeholders for citations and unsupported spans. */
export function segmentsToMarkdown(segments: Segment[]): string {
  return segments
    .map((s) => {
      const text = markLoaded(s);
      if (s.status === "cited") return text + CITE(s.sources);
      if (s.status === "unsupported" || s.status === "invalid") {
        // keep leading/trailing whitespace outside the marker so markdown structure survives
        const m = text.match(/^(\s*)([\s\S]*?)(\s*)$/);
        return m && m[2] ? `${m[1]}${U_OPEN}${m[2]}${U_CLOSE}${m[3]}` : text;
      }
      return text;
    })
    .join("");
}

/** Render answer markdown to sanitised HTML with clickable [Source n] badges. */
export function renderAnswer(md: string): string {
  let html = marked.parse(md, { async: false }) as string;
  html = html.replace(/⁣⟦S:([\d,]+)⟧⁣/g, (_m, nums: string) =>
    nums
      .split(",")
      .map((n) => `<button type="button" class="cite" data-source="${n}" aria-label="Open source ${n}">${n}</button>`)
      .join(""),
  );
  html = html
    .replace(/⁣⟦U⟧⁣/g, '<span class="unsupported" title="Not directly supported by a cited source">')
    .replace(/⁣⟦\/U⟧⁣/g, "</span>")
    .replace(/⁣⟦L⟧⁣/g, '<span class="loaded" title="A judgemental word in the briefing\'s own voice, not a quotation">')
    .replace(/⁣⟦\/L⟧⁣/g, "</span>");
  return DOMPurify.sanitize(html, { ADD_ATTR: ["data-source", "aria-label"] });
}

/** Plain streaming text (no citations yet). */
export function renderPlain(md: string): string {
  return DOMPurify.sanitize(marked.parse(md, { async: false }) as string);
}

/** Split text into parts, marking exact quotes to highlight. */
export function highlightParts(text: string, quotes: string[]): { text: string; hit: boolean }[] {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const ranges: [number, number][] = [];
  for (const q of quotes.map(norm).filter((q) => q.length > 3)) {
    const i = text.indexOf(q);
    if (i >= 0) ranges.push([i, i + q.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const parts: { text: string; hit: boolean }[] = [];
  let pos = 0;
  for (const [s, e] of ranges) {
    if (s < pos) continue;
    if (s > pos) parts.push({ text: text.slice(pos, s), hit: false });
    parts.push({ text: text.slice(s, e), hit: true });
    pos = e;
  }
  if (pos < text.length) parts.push({ text: text.slice(pos), hit: false });
  return parts;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}
