import { describe, expect, it } from "vitest";
import { parseChunk } from "../api";
import { highlightParts, renderAnswer, segmentsToMarkdown } from "../render";
import type { Segment } from "../types";

const seg = (text: string, status: Segment["status"], sources: number[] = []): Segment => ({
  text,
  status,
  sources,
  cited: sources.map((n) => ({ source: n, cited_text: "x" })),
});

describe("answer rendering", () => {
  it("turns citations into clickable source badges", () => {
    const html = renderAnswer(segmentsToMarkdown([seg("Ministers cited costs", "cited", [1, 3]), seg(".", "connective")]));
    expect(html).toContain('data-source="1"');
    expect(html).toContain("[Source 3]");
    expect(html).not.toContain("⟦");
  });

  it("highlights unsupported text", () => {
    const html = renderAnswer(segmentsToMarkdown([seg("An uncited claim about 2023.", "unsupported")]));
    expect(html).toContain('class="unsupported"');
  });

  it("sanitises model output", () => {
    const html = renderAnswer(segmentsToMarkdown([seg('<img src=x onerror="alert(1)"> text', "cited", [1])]));
    expect(html).not.toContain("onerror");
  });

  it("keeps markdown lists intact around citations", () => {
    const md = segmentsToMarkdown([seg("- First point", "cited", [1]), seg("\n- Second point", "cited", [2])]);
    const html = renderAnswer(md);
    expect(html.match(/<li>/g)?.length).toBe(2);
  });
});

describe("highlighting", () => {
  it("marks exact cited quotes in the verbatim text", () => {
    const parts = highlightParts("The line to Crewe is delayed. Costs rose.", ["Costs rose."]);
    expect(parts).toEqual([
      { text: "The line to Crewe is delayed. ", hit: false },
      { text: "Costs rose.", hit: true },
    ]);
  });
});

describe("server-sent events", () => {
  it("parses data lines", () => {
    const evs = [...parseChunk('event: text\ndata: {"type":"text","text":"Hi"}')];
    expect(evs).toEqual([{ type: "text", text: "Hi" }]);
  });
});
