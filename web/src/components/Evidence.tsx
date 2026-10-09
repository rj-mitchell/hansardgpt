import { fmtDate } from "../render";
import type { Evidence } from "../types";

const SEAT_LABEL: Record<string, string> = { city: "city seats", town: "town seats", rural: "rural seats" };

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
      <ul className="evidence-groups">
        {Object.entries(evidence.groups).map(([g, n]) => (
          <li key={g}>
            {g} <span className="count">{n}</span>
          </li>
        ))}
      </ul>
      {Object.keys(evidence.seat_types).length > 0 && (
        <p className="muted small">
          MPs' seats:{" "}
          {Object.entries(evidence.seat_types)
            .map(([k, n]) => `${n} ${SEAT_LABEL[k] ?? k}`)
            .join(" · ")}
          {Object.keys(evidence.parties).length > 0 &&
            ` · Parties: ${Object.entries(evidence.parties)
              .map(([p, n]) => `${p} ${n}`)
              .join(", ")}`}
        </p>
      )}
    </section>
  );
}
