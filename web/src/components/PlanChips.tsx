import { useState } from "react";
import type { Meta, Plan } from "../types";

interface Props {
  plan: Plan;
  meta: Meta | null;
  onRerun: (plan: Plan) => void;
  busy: boolean;
}

const OFFICE_LABEL: Record<string, string> = {
  gov: "Government ministers",
  shadow: "Shadow ministers",
  chair: "Committee chairs",
  backbench: "Backbenchers",
};

type ChipDef = { key: string; label: string; remove: (p: Plan) => Plan };

export function chipsFor(plan: Plan, meta: Meta | null): ChipDef[] {
  const f = plan.filters;
  const without = (field: keyof Plan["filters"], value: string) => (p: Plan) => ({
    ...p,
    filters: { ...p.filters, [field]: (p.filters[field] as string[]).filter((v) => v !== value) },
  });
  const chips: ChipDef[] = [];
  if (f.date_from) chips.push({ key: "from", label: `From ${f.date_from}`, remove: (p) => ({ ...p, filters: { ...p.filters, date_from: null } }) });
  if (f.date_to) chips.push({ key: "to", label: `To ${f.date_to}`, remove: (p) => ({ ...p, filters: { ...p.filters, date_to: null } }) });
  f.houses.forEach((h) => chips.push({ key: `h-${h}`, label: h === "lords" ? "House of Lords" : "House of Commons", remove: without("houses", h) }));
  f.regions.forEach((r) => chips.push({ key: `r-${r}`, label: `MPs in ${r}`, remove: without("regions", r) }));
  f.parties.forEach((x) =>
    chips.push({ key: `p-${x}`, label: meta?.parties.find((p) => p.id === x)?.name ?? x, remove: without("parties", x) }),
  );
  f.offices.forEach((o) => chips.push({ key: `o-${o}`, label: OFFICE_LABEL[o] ?? o, remove: without("offices", o) }));
  plan.speakers.forEach((s) =>
    chips.push({
      key: `s-${s.person_id}`,
      label: `Speaker: ${s.name}`,
      remove: (p) => ({
        ...p,
        speakers: p.speakers.filter((x) => x.person_id !== s.person_id),
        filters: { ...p.filters, person_ids: p.filters.person_ids.filter((x) => x !== s.person_id) },
      }),
    }),
  );
  plan.portfolios.forEach((x) =>
    chips.push({
      key: `b-${x}`,
      label: `Boost: ${meta?.portfolios[x]?.split(":")[0] ?? x}`,
      remove: (p) => ({ ...p, portfolios: p.portfolios.filter((v) => v !== x) }),
    }),
  );
  return chips;
}

export function PlanChips({ plan, meta, onRerun, busy }: Props) {
  const [draft, setDraft] = useState<Plan>(plan);
  const [editing, setEditing] = useState(false);
  const chips = chipsFor(draft, meta);
  const changed = JSON.stringify(draft) !== JSON.stringify(plan);

  return (
    <div className="plan" aria-label="Search filters used">
      <div className="plan-head">
        <span className="muted small">{plan.interpretation || "Filters"}</span>
        <button type="button" className="link small" onClick={() => setEditing(!editing)}>
          {editing ? "Close" : "Edit filters"}
        </button>
      </div>
      <ul className="chips">
        <li className="chip search-text" title="Words used for retrieval">
          “{draft.search_text}”
        </li>
        {chips.map((c) => (
          <li key={c.key} className="chip">
            {c.label}
            <button type="button" aria-label={`Remove ${c.label}`} onClick={() => setDraft(c.remove(draft))}>
              ×
            </button>
          </li>
        ))}
        {plan.unresolved_speakers.length > 0 && (
          <li className="chip warn">No member found for: {plan.unresolved_speakers.join(", ")}</li>
        )}
      </ul>
      {editing && <PlanEditor draft={draft} meta={meta} onChange={setDraft} />}
      {(changed || editing) && (
        <button type="button" className="secondary" disabled={busy} onClick={() => onRerun(draft)}>
          Re-run with these filters
        </button>
      )}
    </div>
  );
}

function PlanEditor({ draft, meta, onChange }: { draft: Plan; meta: Meta | null; onChange: (p: Plan) => void }) {
  const f = draft.filters;
  const setF = (patch: Partial<Plan["filters"]>) => onChange({ ...draft, filters: { ...f, ...patch } });
  const toggle = (field: "houses" | "offices" | "regions", value: string) =>
    setF({ [field]: f[field].includes(value) ? f[field].filter((v) => v !== value) : [...f[field], value] });
  return (
    <div className="plan-editor">
      <label>
        Search words
        <input value={draft.search_text} onChange={(e) => onChange({ ...draft, search_text: e.target.value })} />
      </label>
      <div className="row">
        <label>
          From
          <input type="date" value={f.date_from ?? ""} onChange={(e) => setF({ date_from: e.target.value || null })} />
        </label>
        <label>
          To
          <input type="date" value={f.date_to ?? ""} onChange={(e) => setF({ date_to: e.target.value || null })} />
        </label>
      </div>
      <fieldset>
        <legend>House</legend>
        {["commons", "lords"].map((h) => (
          <label key={h}>
            <input type="checkbox" checked={f.houses.includes(h)} onChange={() => toggle("houses", h)} />
            {h === "commons" ? "Commons" : "Lords"}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Speaker role</legend>
        {Object.entries(OFFICE_LABEL).map(([k, v]) => (
          <label key={k}>
            <input type="checkbox" checked={f.offices.includes(k)} onChange={() => toggle("offices", k)} />
            {v}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>MPs' region (Commons only)</legend>
        <div className="grid">
          {(meta?.regions ?? []).map((r) => (
            <label key={r}>
              <input type="checkbox" checked={f.regions.includes(r)} onChange={() => toggle("regions", r)} />
              {r}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        Party
        <select
          multiple
          value={f.parties}
          onChange={(e) => setF({ parties: Array.from(e.target.selectedOptions).map((o) => o.value) })}
        >
          {(meta?.parties ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
