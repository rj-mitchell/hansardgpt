import { fmtDate } from "../render";

export interface InterestItem {
  summary: string;
  details: [string, string][];
  registered: string | null;
  published: string | null;
  children: InterestItem[];
}
export interface Interests {
  edition: string | null;
  source: string | null;
  official: string;
  listed: boolean;
  categories: { type: string; name: string; items: InterestItem[] }[];
}

const MONEY = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

function show(name: string, value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return fmtDate(value);
  if (/^(value|amount)$/i.test(name) && /^\d+(\.\d+)?$/.test(value)) return MONEY.format(Number(value));
  return value;
}

function Item({ item }: { item: InterestItem }) {
  return (
    <li className="interest">
      <p className="interest-summary">{item.summary}</p>
      {item.details.length > 0 && (
        <dl className="interest-details small">
          {item.details.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{show(k, v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.registered && <p className="muted small">Registered {item.registered}</p>}
      {item.children.length > 0 && (
        <details className="interest-children">
          <summary>
            {item.children.length} payment{item.children.length === 1 ? "" : "s"} or specific piece
            {item.children.length === 1 ? "" : "s"} of work
          </summary>
          <ul>
            {item.children.map((c, k) => (
              <Item key={k} item={c} />
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

/** A member's entries in the latest Register of Members' Financial Interests, as they registered them. */
export function InterestsSection({ interests, name, isMP }: { interests: Interests; name: string; isMP: boolean }) {
  if (!interests.listed && !isMP) return null;
  const total = interests.categories.reduce((n, c) => n + c.items.length, 0);
  return (
    <section aria-labelledby="h-interests">
      <h2 id="h-interests">Registered interests</h2>
      <p>
        {interests.listed && total > 0
          ? `${name} has ${total} entr${total === 1 ? "y" : "ies"} in the Register of Members' Financial Interests`
          : `${name} has no entries in the Register of Members' Financial Interests`}
        {interests.edition ? `, as published on ${fmtDate(interests.edition)}` : ""}.
      </p>
      <p className="muted small">
        MPs must register their jobs and earnings, donations, gifts, visits abroad, property and shareholdings. These
        are declarations, shown as registered: an entry is not a finding of wrongdoing, and being listed here does not
        mean an interest influenced anything the member said or did. Donors' addresses are left out. Read the{" "}
        <a href={interests.official}>official register</a>.
      </p>
      {interests.categories.map((c) => (
        <details key={c.type + c.name} className="interest-category">
          <summary>
            {c.name} ({c.items.length})
          </summary>
          <ul className="interests">
            {c.items.map((it, k) => (
              <Item key={k} item={it} />
            ))}
          </ul>
        </details>
      ))}
    </section>
  );
}
