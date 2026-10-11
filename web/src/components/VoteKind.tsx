import type { VoteType } from "../types";

/** The kind of vote (amendment, second reading…) as a link to its glossary entry, with what it usually means. */
export function VoteKind({ vt, detail = false }: { vt?: VoteType; detail?: boolean }) {
  if (!vt || vt.kind === "other") return null;
  return (
    <span className="vote-kind">
      <a className="vote-kind-label" href={`/glossary#vote-${vt.kind.replace(/_/g, "-")}`}>
        {vt.label}
      </a>
      {detail && (
        <>
          {vt.question && (
            <span className="vote-kind-question">
              {" "}
              The question put: “{vt.question}”.
            </span>
          )}
          {vt.outcome && <span className="vote-kind-outcome"> Recorded outcome: {vt.outcome}</span>}
          <span className="vote-kind-note"> {vt.note}</span>
        </>
      )}
    </span>
  );
}

/** The kinds present in a list of votes, each with its note: a key shown once under a table. */
export function VoteKindKey({ types }: { types: (VoteType | undefined)[] }) {
  const seen = new Map<string, VoteType>();
  for (const t of types) if (t && t.kind !== "other" && !seen.has(t.kind)) seen.set(t.kind, t);
  if (seen.size === 0) return null;
  return (
    <dl className="vote-kind-key small">
      {[...seen.values()].map((t) => (
        <div key={t.kind}>
          <dt>{t.label}</dt>
          <dd>{t.note}</dd>
        </div>
      ))}
    </dl>
  );
}
