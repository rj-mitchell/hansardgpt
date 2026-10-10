import { useMemo, useState } from "react";
import { api } from "../api";
import { briefingWithSources, referencesOnly } from "../export";
import { fmtDate, renderAnswer, renderPlain, segmentsToMarkdown } from "../render";
import type { Answer, Highlight, SourceCard } from "../types";
import { ReportProblem } from "./ReportProblem";

interface Props {
  question: string;
  answer?: Answer | null;
  streamText: string;
  sources: SourceCard[];
  briefingKey?: string;
  briefingId?: string;
  preparedAt?: string;
  recordsUpTo?: string | null;
  onCite: (h: Highlight) => void;
}

export function AnswerView({
  question,
  answer,
  streamText,
  sources,
  briefingKey,
  briefingId,
  preparedAt,
  recordsUpTo,
  onCite,
}: Props) {
  const link = briefingId ? `${window.location.origin}/b/${briefingId}` : undefined;
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
      {answer && !answer.no_records && (
        <>
          <p className="ai-note">
            Written by AI (Claude) from the cited Hansard records only. Check the sources before relying on it.
            {preparedAt &&
              ` Prepared ${fmtDate(preparedAt.slice(0, 10))}${recordsUpTo ? ` from records up to ${fmtDate(recordsUpTo)}` : ""}.`}
          </p>
          <div className="answer-actions">
            {link && <ShareButton url={link} title={question} />}
            <CopyButton label="Copy with sources" text={() => briefingWithSources(question, answer, sources, new Date(), link)} />
            <CopyButton label="Copy references" text={() => referencesOnly(answer, sources)} />
            <Feedback question={question} briefingKey={briefingKey} />
          </div>
          <ReportProblem briefingId={briefingId} />
        </>
      )}
    </div>
  );
}

/** The phone's share sheet where there is one; otherwise copy the link. */
function ShareButton({ url, title }: { url: string; title: string }) {
  const [done, setDone] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";
  async function share() {
    try {
      if (canShare) await navigator.share({ url, title: `${title} — Where They Stand` });
      else {
        await navigator.clipboard.writeText(url);
        setDone(true);
        setTimeout(() => setDone(false), 2000);
      }
    } catch {
      /* cancelled or unavailable */
    }
  }
  return (
    <button type="button" className="primary" onClick={() => void share()}>
      {done ? "Link copied" : canShare ? "Share" : "Copy link"}
    </button>
  );
}

function CopyButton({ label, text }: { label: string; text: () => string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text());
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      /* clipboard unavailable: nothing to do */
    }
  }
  return (
    <button type="button" className="secondary" onClick={() => void copy()}>
      {done ? "Copied" : label}
    </button>
  );
}

function Feedback({ question, briefingKey }: { question: string; briefingKey?: string }) {
  const [sent, setSent] = useState<boolean | null>(null);
  if (sent !== null) return <p className="feedback muted small">Thank you for the feedback.</p>;
  const send = (useful: boolean) => {
    setSent(useful);
    void api.feedback(question, useful, briefingKey).catch(() => undefined);
  };
  return (
    <p className="feedback">
      <span>Was this briefing useful?</span>
      <button type="button" className="link" onClick={() => send(true)}>
        Yes
      </button>
      <button type="button" className="link" onClick={() => send(false)}>
        No
      </button>
    </p>
  );
}

export function Grounding({ answer }: { answer: Answer }) {
  if (answer.no_records) {
    return <p className="grounding neutral">No matching records in the archive for this question and these filters.</p>;
  }
  const flagged = answer.unsupported_segments;
  const loaded = answer.loaded_words ?? 0;
  return (
    <p className={flagged || loaded ? "grounding warn" : "grounding ok"}>
      {flagged
        ? `${flagged} passage${flagged === 1 ? "" : "s"} not directly supported by a cited source (highlighted). Treat with caution.`
        : `Every substantive statement is cited (${answer.citations_total} citation${answer.citations_total === 1 ? "" : "s"}, each checked against the source text).`}
      {loaded > 0 &&
        ` ${loaded} judgemental word${loaded === 1 ? "" : "s"} in the briefing's own voice (underlined); the record itself should be checked.`}
      {answer.citations_invalid > 0 && ` ${answer.citations_invalid} citation(s) could not be verified and were removed.`}
    </p>
  );
}
