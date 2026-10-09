import { useEffect, useRef } from "react";
import { fmtDate, highlightParts } from "../render";
import type { Highlight, SourceCard, Speaker } from "../types";

export function speakerLine(sp: Speaker | null | undefined, raw?: string | null): string {
  if (!sp || !sp.name) return raw || "Unattributed";
  const seat = sp.settlement ? ` (${sp.settlement} seat)` : "";
  const where = sp.constituency ? `MP for ${sp.constituency}${seat}` : sp.house === "lords" ? "House of Lords" : null;
  return [sp.name, [sp.party, where].filter(Boolean).join(", ")].filter(Boolean).join(" — ");
}

export function roleTitles(sp: Speaker | null | undefined): string[] {
  return (sp?.offices ?? []).filter((o) => ["gov", "shadow", "chair"].includes(o.kind)).map((o) => o.title);
}

export function SourceList({
  sources,
  onOpen,
  open,
}: {
  sources: SourceCard[];
  onOpen: (h: Highlight) => void;
  open: boolean;
}) {
  if (!sources.length) return null;
  const groups: [string, SourceCard[]][] = [];
  for (const s of sources) {
    const g = s.kind === "division" ? "Votes (divisions)" : s.group ?? "Other";
    const hit = groups.find(([name]) => name === g);
    if (hit) hit[1].push(s);
    else groups.push([g, [s]]);
  }
  return (
    <details className="sources" open={open}>
      <summary>
        {open ? "" : "Show "}all {sources.length} source{sources.length === 1 ? "" : "s"}, by speaker group
      </summary>
      {groups.map(([g, items]) => (
        <section key={g} className="source-group">
          <h3>{g}</h3>
          <ol>
            {items.map((s) => (
          <li key={s.n}>
            <button type="button" className="source-card" onClick={() => onOpen({ source: s.n, quotes: [] })}>
              <span className="badge">{s.n}</span>
              <span className="source-meta">
                {s.kind === "division" ? (
                  <strong>
                    Division {s.number}: {s.major_heading}
                  </strong>
                ) : (
                  <strong>{speakerLine(s.speaker, s.speaker_name_raw)}</strong>
                )}
                {roleTitles(s.speaker).length > 0 && <span className="role">{roleTitles(s.speaker).join("; ")}</span>}
                <span className="muted small">
                  {fmtDate(s.date)} · {s.chamber}
                  {s.colnum ? ` · col. ${s.colnum}` : s.uin ? ` · ${s.uin}` : ""}
                  {s.heading ? ` · ${s.heading}` : ""}
                </span>
              </span>
            </button>
          </li>
            ))}
          </ol>
        </section>
      ))}
    </details>
  );
}

export function SourceDrawer({
  source,
  quotes,
  onClose,
}: {
  source: SourceCard | null;
  quotes: string[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!source) return;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [source, onClose]);
  useEffect(() => {
    const first = ref.current?.querySelector("mark");
    if (first && typeof first.scrollIntoView === "function") first.scrollIntoView({ block: "center" });
  }, [source, quotes]);

  if (!source) return null;
  const sp = source.speaker;
  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-label={`Source ${source.n}`} tabIndex={-1} ref={ref}>
      <header>
        <span className="badge">{source.n}</span>
        <h2>{source.kind === "division" ? `Division ${source.number}` : speakerLine(sp, source.speaker_name_raw)}</h2>
        <button type="button" className="close" onClick={onClose} aria-label="Close source">
          ×
        </button>
      </header>

      <dl className="facts">
        {source.kind === "record" && (
          <>
            <dt>Speaker</dt>
            <dd>
              {sp?.name ?? source.speaker_name_raw ?? "Unattributed"}
              {sp?.other_names && sp.other_names.length > 0 && (
                <span className="muted small"> (also recorded as {sp.other_names.join("; ")})</span>
              )}
            </dd>
            <dt>Party</dt>
            <dd>{sp?.party ?? "—"}</dd>
            <dt>{sp?.house === "lords" ? "House" : "Constituency"}</dt>
            <dd>
              {sp?.constituency ? `${sp.constituency}${sp.region ? ` (${sp.region})` : ""}` : sp?.house === "lords" ? "House of Lords" : "—"}
            </dd>
            <dt>Role on {fmtDate(source.date)}</dt>
            <dd>{roleTitles(sp).length ? roleTitles(sp).join("; ") : "Backbencher (no ministerial or committee-chair post)"}</dd>
          </>
        )}
        <dt>Record</dt>
        <dd>
          {source.chamber}, {fmtDate(source.date)}
          {source.time ? `, ${source.time}` : ""}
          {source.heading ? ` — ${source.heading}` : ""}
        </dd>
        <dt>{source.colnum ? "Hansard column" : source.uin ? "Reference" : "Column"}</dt>
        <dd>{source.colnum ?? source.uin ?? "Not given in the source data"}</dd>
        <dt>Links</dt>
        <dd className="links">
          {source.official_url && (
            <a href={source.official_url} target="_blank" rel="noreferrer">
              {source.url_kind === "sitting" ? "Official Hansard (sitting day)" : "Official Parliament record"}
            </a>
          )}
          <a href={source.twfy_url} target="_blank" rel="noreferrer">
            TheyWorkForYou (exact record)
          </a>
        </dd>
      </dl>

      {source.kind === "division" ? (
        <DivisionDetail source={source} />
      ) : (
        <section className="verbatim" aria-label="Verbatim text">
          {source.context && (
            <blockquote className="question">
              <strong>Question asked:</strong> {source.context}
            </blockquote>
          )}
          {source.text.split("\n\n").map((para, i) => (
            <p key={i}>
              {highlightParts(para, quotes).map((part, j) => (part.hit ? <mark key={j}>{part.text}</mark> : <span key={j}>{part.text}</span>))}
            </p>
          ))}
        </section>
      )}

      {source.ranking && (
        <details className="ranking">
          <summary>Why this source ranked here</summary>
          <dl>
            <dt>Relevance</dt>
            <dd>
              {source.ranking.relevance.toFixed(2)} (keyword {source.ranking.keyword?.toFixed(2) ?? "—"}, semantic{" "}
              {source.ranking.semantic?.toFixed(2) ?? "—"})
            </dd>
            <dt>Recency factor</dt>
            <dd>×{source.ranking.recency.toFixed(2)}</dd>
            <dt>Role factor</dt>
            <dd>
              ×{source.ranking.authority.toFixed(2)} — {source.ranking.authority_reason}
            </dd>
            <dt>Score</dt>
            <dd>{source.ranking.score.toFixed(3)}</dd>
          </dl>
        </details>
      )}
      <p className="muted small licence">Contains Parliamentary information licensed under the Open Parliament Licence v3.0.</p>
    </aside>
  );
}

function DivisionDetail({ source }: { source: SourceCard }) {
  return (
    <section className="division">
      <p>
        <strong>{[source.major_heading, source.minor_heading].filter(Boolean).join(" — ")}</strong>
      </p>
      <p>
        Ayes {source.ayes} · Noes {source.noes}
      </p>
      {source.party_votes && (
        <table>
          <caption className="muted small">Votes by party ({source.scope_note})</caption>
          <thead>
            <tr>
              <th>Party</th>
              <th>Aye</th>
              <th>No</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(source.party_votes).map(([p, v]) => (
              <tr key={p}>
                <td>{p}</td>
                <td>{v.aye}</td>
                <td>{v.no}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>Voted against their own party's majority</h3>
      {source.rebels && source.rebels.length > 0 ? (
        <ul>
          {source.rebels.map((r, i) => (
            <li key={i}>
              {r.name} ({r.party}
              {r.constituency ? `, ${r.constituency}` : ""}) voted {r.vote}; party majority {r.majority}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Nobody in scope.</p>
      )}
    </section>
  );
}
