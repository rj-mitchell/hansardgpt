/** A member's page: who they are, seats and majorities, roles, recent contributions and voting record. */
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./pages";
import { Timeline } from "./components/Timeline";
import { fmtDate } from "./render";

interface Result {
  election: string;
  date: string;
  majority: number;
  pct: number | null;
  band: string | null;
  party: string | null;
}
interface PersonData {
  number: number;
  name: string;
  slug: string;
  other_names: string[];
  status: string;
  age: number | null;
  age_approximate: boolean | null;
  first_elected: string | null;
  current: { house: string; constituency: string | null; party: string | null } | null;
  memberships: { house: string; constituency: string | null; party: string | null; start: string; end: string | null }[];
  offices: { kind: string; title: string; start: string; end: string | null }[];
  seats: { constituency: string; start: string; end: string | null; results: Result[] }[];
  contributions: {
    record_id: string;
    date: string;
    chamber: string;
    record_type: string;
    heading: string;
    excerpt: string;
    twfy_url: string;
    official_url: string | null;
  }[];
  voting: {
    votes: number;
    rebellions: number;
    since: string | null;
    until: string | null;
    method: string;
    recent_rebellions: { date: string; title: string; vote: string; party_majority: string; twfy_url: string }[];
  } | null;
}

const BAND: Record<string, string> = { marginal: "marginal seat", middle: "majority 10% to 20%", safe: "safe seat" };
const KIND: Record<string, string> = {
  gov: "Government",
  shadow: "Opposition",
  chair: "Committee chair",
  whip: "Whip",
  parliamentary: "Parliamentary",
};
const span = (start: string, end: string | null) => `${fmtDate(start)} – ${end ? fmtDate(end) : "now"}`;

function Person({ number }: { number: string }) {
  const [shown, setShown] = useState("");
  const [p, setP] = useState<PersonData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  useEffect(() => {
    fetch(`/api/people/${number}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "This member could not be loaded.");
        return r.json() as Promise<PersonData>;
      })
      .then((d) => {
        setP(d);
        document.title = `${d.name} — Where They Stand`;
        const want = `/people/${d.number}/${d.slug}`;
        if (window.location.pathname !== want) window.history.replaceState(null, "", want);
      })
      .catch((e: Error) => setError(e.message));
  }, [number]);

  if (error) return <p role="alert">{error}</p>;
  if (!p) return <p className="muted">Loading…</p>;
  const ask = (q: string) => `/?q=${encodeURIComponent(q)}`;
  return (
    <article>
      <p className="eyebrow">{p.current?.house === "lords" ? "House of Lords" : p.current ? "House of Commons" : "Former member"}</p>
      <h1>{p.name}</h1>
      <p className="lede">
        {p.status}
        {p.age != null && `. Age ${p.age_approximate ? "about " : ""}${p.age}`}
        {p.first_elected && p.memberships.some((m) => m.house === "commons") && `. First elected ${fmtDate(p.first_elected)}`}.
      </p>
      {p.other_names.length > 0 && <p className="muted small">Also recorded as {p.other_names.join("; ")}.</p>}

      <form
        className="ask-about"
        onSubmit={(e) => {
          e.preventDefault();
          window.location.href = ask(`What has ${p.name} said about ${topic.trim() || "…"}?`);
        }}
      >
        <label htmlFor="topic">What has {p.name} said about…</label>
        <div className="ask-row">
          <input id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="a topic, such as housing" />
          <button type="submit" className="primary" disabled={!topic.trim()}>
            Ask
          </button>
          <button type="button" className="secondary" disabled={!topic.trim()} onClick={() => setShown(topic.trim())}>
            Timeline
          </button>
        </div>
        <p className="muted small">
          Ask writes a sourced briefing. Timeline lists what they said and how they voted on it, in date order.
        </p>
      </form>
      {shown && (
        <>
          <h2 id="h-timeline">Timeline: {shown}</h2>
          <Timeline query={`person=${number}&q=${encodeURIComponent(shown)}`} showSpeaker={false} />
        </>
      )}

      {p.seats.length > 0 && (
        <section aria-labelledby="h-seats">
          <h2 id="h-seats">Seats and majorities</h2>
          {p.seats.map((s) => (
            <div key={s.constituency + s.start} className="seat">
              <h3>
                {s.constituency} <span className="muted small">({span(s.start, s.end)})</span>
              </h3>
              {s.results.length > 0 ? (
                <ul>
                  {s.results.map((r) => (
                    <li key={r.date}>
                      {r.election[0].toUpperCase() + r.election.slice(1)}: majority {r.majority.toLocaleString("en-GB")}
                      {r.pct != null && `, ${r.pct}% of votes cast`}
                      {r.band && <span className="muted"> · {BAND[r.band]}</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">Election results before 2010 are not included.</p>
              )}
            </div>
          ))}
        </section>
      )}

      {p.offices.length > 0 && (
        <section aria-labelledby="h-roles">
          <h2 id="h-roles">Roles</h2>
          <ul className="roles">
            {p.offices.slice(0, 30).map((o) => (
              <li key={o.title + o.start}>
                <strong>{o.title}</strong> <span className="muted small">{KIND[o.kind] ?? o.kind}, {span(o.start, o.end)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="h-recent">
        <h2 id="h-recent">Recent contributions</h2>
        {p.contributions.length === 0 ? (
          <p className="muted">No contributions in the record since 2010.</p>
        ) : (
          <ol className="contributions">
            {p.contributions.map((c) => (
              <li key={c.record_id}>
                <p className="muted small">
                  {fmtDate(c.date)} · {c.chamber}
                  {c.heading ? ` · ${c.heading}` : ""}
                </p>
                <p>{c.excerpt.length >= 320 ? `${c.excerpt.trimEnd()}…` : c.excerpt}</p>
                <p className="small">
                  <a href={c.twfy_url}>Read in full</a>
                  {c.official_url && (
                    <>
                      {" · "}
                      <a href={c.official_url}>Official record</a>
                    </>
                  )}
                </p>
              </li>
            ))}
          </ol>
        )}
      </section>

      {p.voting && p.voting.votes > 0 && (
        <section aria-labelledby="h-votes">
          <h2 id="h-votes">Voting record</h2>
          <p>
            {p.voting.votes.toLocaleString("en-GB")} votes recorded between {fmtDate(p.voting.since)} and{" "}
            {fmtDate(p.voting.until)}, of which {p.voting.rebellions.toLocaleString("en-GB")} were against the majority of
            their own party.
          </p>
          {p.voting.recent_rebellions.length > 0 && (
            <>
              <h3>Most recent votes against their party's majority</h3>
              <ul>
                {p.voting.recent_rebellions.map((r) => (
                  <li key={r.date + r.title}>
                    {fmtDate(r.date)}: <a href={r.twfy_url}>{r.title || "Division"}</a>. Voted {r.vote}; most of their party
                    voted {r.party_majority}.
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">{p.voting.method}</p>
        </section>
      )}

      <section aria-labelledby="h-history">
        <h2 id="h-history">Membership</h2>
        <ul>
          {[...p.memberships].reverse().map((m) => (
            <li key={m.house + m.start}>
              {m.house === "commons" ? `MP for ${m.constituency ?? "—"}` : "House of Lords"}
              {m.party ? `, ${m.party}` : ""} <span className="muted small">({span(m.start, m.end)})</span>
            </li>
          ))}
        </ul>
      </section>
      <p className="muted small">
        From Hansard, mySociety's member records and the UK Parliament's Members data. See the{" "}
        <a href="/methodology">methodology</a>.
      </p>
    </article>
  );
}

const number = window.location.pathname.match(/^\/people\/(\d+)/)?.[1];
createRoot(document.getElementById("person-root")!).render(
  <StrictMode>{number ? <Person number={number} /> : <p role="alert">No member was given.</p>}</StrictMode>,
);
