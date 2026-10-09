import { useMemo } from "react";
import { renderAnswer, renderPlain, segmentsToMarkdown } from "../render";
import type { Answer, Highlight } from "../types";

interface Props {
  answer?: Answer | null;
  streamText: string;
  onCite: (h: Highlight) => void;
}

export function AnswerView({ answer, streamText, onCite }: Props) {
  const html = useMemo(
    () => (answer ? renderAnswer(segmentsToMarkdown(answer.segments)) : renderPlain(streamText)),
    [answer, streamText],
  );

  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("button.cite");
    if (!btn || !answer) return;
    const n = Number(btn.dataset.source);
    const quotes = answer.segments.flatMap((s) => s.cited.filter((c) => c.source === n).map((c) => c.cited_text));
    onCite({ source: n, quotes });
  }

  return (
    <div className="answer">
      {/* eslint-disable-next-line react/no-danger -- sanitised with DOMPurify in render.ts */}
      <div className={answer ? "answer-body" : "answer-body streaming"} onClick={onClick} dangerouslySetInnerHTML={{ __html: html }} />
      {answer && <Grounding answer={answer} />}
    </div>
  );
}

export function Grounding({ answer }: { answer: Answer }) {
  if (answer.no_records) {
    return <p className="grounding neutral">No matching records in the archive for this question and these filters.</p>;
  }
  const flagged = answer.unsupported_segments;
  return (
    <p className={flagged ? "grounding warn" : "grounding ok"}>
      {flagged
        ? `${flagged} passage${flagged === 1 ? "" : "s"} not directly supported by a cited source (highlighted). Treat with caution.`
        : `Every substantive statement is cited (${answer.citations_total} citation${answer.citations_total === 1 ? "" : "s"}, each checked against the source text).`}
      {answer.citations_invalid > 0 && ` ${answer.citations_invalid} citation(s) could not be verified and were removed.`}
    </p>
  );
}
