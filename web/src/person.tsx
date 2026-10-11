/** A member's page: who they are, seats and majorities, roles, recent contributions and voting record. */
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./pages";
import { Timeline } from "./components/Timeline";
import { EdmList, type EdmRow } from "./components/EdmList";
import { type Interests, InterestsSection } from "./components/Interests";
import { VoteKind } from "./components/VoteKind";
import { fmtDate } from "./render";
import type { VoteType } from "./types";

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
    debate_path: string | null;
  }[];
  voting: {
    votes: number;
    rebellions: number;
    since: string | null;
    until: string | null;
    method: string;
    recent_rebellions: {
      date: string;
      title: string;
      vote: string;
      party_majority: string;
      twfy_url: string;
      vote_type?: VoteType;
    }[];
  } | null;
  edms?: { tabled: number; signed: number; recent: EdmRow[] } | null;
  interests?: Interests | null;
  devolved?: {
    memberships: { legislature: string; body: string; member: string; seat: string | null; party: string | null; start: string; end: string | null }[];
    counts: Record<string, number>;
    recent: { legislature: string; key: string; date: string; ord: number; major: string | null; excerpt: string }[];
  } | null;
  committee_evidence?: { id: number; date: string | null; role: string | null; committees: string | null; inquiry: string | null; url: string }[];
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
        <p className="small feed-link">
          <a href={`/feeds/people/${p.number}.xml`}>Follow what {p.name} says in a feed reader (RSS)</a>
        </p>
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
                  <a href={c.debate_path ?? c.twfy_url}>Read in full</a>
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
                    {fmtDate(r.date)}: <a href={r.twfy_url}>{r.title || "Division"}</a>
                    {r.vote_type && r.vote_type.kind !== "other" && (
                      <>
                        {" "}
                        (<VoteKind vt={r.vote_type} />)
                      </>
                    )}
                    . Voted {r.vote}; most of their party voted {r.party_majority}.
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">{p.voting.method}</p>
        </section>
      )}

      {p.devolved && (
        <section aria-labelledby="h-devolved">
          <h2 id="h-devolved">In the devolved parliaments</h2>
          <ul>
            {p.devolved.memberships.map((m, k) => (
              <li key={k}>
                {m.member} for {m.seat ?? "an unknown seat"} ({m.body}){m.party ? `, ${m.party}` : ""}{" "}
                <span className="muted small">
                  ({fmtDate(m.start)} – {m.end ? fmtDate(m.end) : "now"})
                </span>
              </li>
            ))}
          </ul>
          {p.devolved.recent.length > 0 && (
            <>
              <h3>Recent contributions</h3>
              <ol className="contributions">
                {p.devolved.recent.map((c) => (
                  <li key={`${c.key}-${c.ord}`}>
                    <p className="muted small">
                      {fmtDate(c.date)}
                      {c.major ? ` · ${c.major}` : ""}
                    </p>
                    <p>{c.excerpt.length >= 320 ? `${c.excerpt.trimEnd()}…` : c.excerpt}</p>
                    <p className="small">
                      <a href={`/devolved/${c.legislature}/${c.key}#s${c.ord}`}>Read it in the sitting</a>
                    </p>
                  </li>
                ))}
              </ol>
            </>
          )}
          <p className="muted small">
            Collected since 2021; see <a href="/devolved">devolved parliaments</a>.
          </p>
        </section>
      )}

      {p.committee_evidence && p.committee_evidence.length > 0 && (
        <section aria-labelledby="h-evidence">
          <h2 id="h-evidence">Evidence to committees</h2>
          <p className="muted small">Sessions where {p.name} answered a committee's questions as a witness, most recent first.</p>
          <ul className="edm-list">
            {p.committee_evidence.map((s) => (
              <li key={s.id}>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.date ? fmtDate(s.date) : "Session"}
                </a>
                : {s.committees}
                {s.inquiry ? ` · ${s.inquiry}` : ""}
                {s.role && <span className="muted small"> ({s.role})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.interests && (
        <InterestsSection interests={p.interests} name={p.name} isMP={p.current?.house === "commons"} />
      )}

      {p.edms && p.edms.tabled + p.edms.signed > 0 && (
        <section aria-labelledby="h-edms">
          <h2 id="h-edms">Early day motions</h2>
          <p>
            Tabled {p.edms.tabled.toLocaleString("en-GB")} and signed {p.edms.signed.toLocaleString("en-GB")} early
            day motion{p.edms.signed === 1 ? "" : "s"} since 2010.{" "}
            <a href={`/edms?person=${p.number}`}>See them all</a>
          </p>
          <h3>Most recent</h3>
          <EdmList items={p.edms.recent} />
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
