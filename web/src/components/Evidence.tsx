import { fmtDate } from "../render";
import type { Evidence } from "../types";

const SEAT_LABEL: Record<string, string> = { city: "City", town: "Town", rural: "Rural" };

/** One labelled row of counts, e.g. Parties: Labour 7 · Conservative 4. Shown so readers can judge balance. */
function EvidenceRow({ label, counts }: { label: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (!entries.length) return null;
  return (
    <div className="evidence-row">
      <span className="evidence-label">{label}</span>
      <ul className="evidence-groups">
        {entries.map(([g, n]) => (
          <li key={g}>
            {g} <span className="count">{n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Deterministic summary of the evidence behind a briefing (computed from the data, not by the model). */
export function EvidenceBar({ evidence }: { evidence?: Evidence }) {
  if (!evidence || evidence.records === 0) return null;
  const years =
    evidence.date_from && evidence.date_to
      ? evidence.date_from.slice(0, 4) === evidence.date_to.slice(0, 4)
        ? fmtDate(evidence.date_from).split(" ").slice(-2).join(" ")
        : `${evidence.date_from.slice(0, 4)}–${evidence.date_to.slice(0, 4)}`
      : "";
  return (
    <section className="evidence" aria-label="Evidence base">
      <p className="evidence-head">
        <strong>Evidence base:</strong> {evidence.records} contribution{evidence.records === 1 ? "" : "s"} from{" "}
        {evidence.speakers} speaker{evidence.speakers === 1 ? "" : "s"}
        {years ? `, ${years}` : ""}
        {evidence.divisions ? `, plus ${evidence.divisions} division${evidence.divisions === 1 ? "" : "s"}` : ""}
      </p>
      <EvidenceRow label="Speakers" counts={evidence.groups} />
      <EvidenceRow label="Parties" counts={evidence.parties} />
      <EvidenceRow
        label="MPs' seats"
        counts={Object.fromEntries(Object.entries(evidence.seat_types).map(([k, n]) => [SEAT_LABEL[k] ?? k, n]))}
      />
    </section>
  );
}
