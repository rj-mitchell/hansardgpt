/** The witness index: who gives oral evidence to committees, how often and to which committees. */
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./pages";
import { getJSON } from "./committeeApi";
import { fmtDate } from "./render";

interface Result {
  query: string;
  since?: string;
  organisations: { organisation: string | null; sessions: number; first: string | null; last: string | null; committees?: string[] }[];
  sessions: { id: number; date: string | null; name: string | null; organisation: string | null; role: string | null; committees: string | null; inquiry_id: number | null; inquiry: string | null; url: string }[];
}

function Witnesses() {
  const [q, setQ] = useState(new URLSearchParams(window.location.search).get("q") ?? "");
  const [d, setD] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    getJSON<Result>(`/api/witnesses?q=${encodeURIComponent(q)}`, "Not found.")
      .then(setD)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load."));
    window.history.replaceState(null, "", q ? `/witnesses?q=${encodeURIComponent(q)}` : "/witnesses");
  }, [q]);
  return (
    <>
      <form
        className="people-search-form"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          const v = new FormData(e.currentTarget).get("q");
          setQ(typeof v === "string" ? v.trim() : "");
        }}
      >
        <label htmlFor="w-q">Organisation or person</label>
        <div className="ask-row">
          <input id="w-q" name="q" defaultValue={q} placeholder="For example: NHS England, Which?, Greenpeace" />
          <button type="submit" className="primary">
            Search
          </button>
        </div>
      </form>
      {error && <p role="alert">{error}</p>}
      {d && (
        <>
          <h2 id="h-orgs">
            {d.query ? `Matching “${d.query}”` : `Heard most often since ${d.since ? fmtDate(d.since) : "two years ago"}`}
          </h2>
          {d.organisations.length === 0 ? (
            <p className="muted">No witnesses match.</p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th scope="col">Organisation</th>
                  <th scope="col">Sessions</th>
                  <th scope="col">Between</th>
                </tr>
              </thead>
              <tbody>
                {d.organisations.map((o) => (
                  <tr key={(o.organisation ?? "") + o.first}>
                    <td>
                      {d.query ? (
                        o.organisation ?? "(no organisation given)"
                      ) : (
                        <button type="button" className="secondary small-button" onClick={() => setQ(o.organisation ?? "")}>
                          {o.organisation}
                        </button>
                      )}
                      {o.committees && o.committees.length > 0 && (
                        <span className="muted small"> · {o.committees.slice(0, 4).join("; ")}{o.committees.length > 4 ? "…" : ""}</span>
                      )}
                    </td>
                    <td>{o.sessions}</td>
                    <td className="small">
                      {o.first ? fmtDate(o.first) : ""}
                      {o.last && o.last !== o.first ? ` – ${fmtDate(o.last)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {d.sessions.length > 0 && (
            <>
              <h2 id="h-sessions">Most recent sessions</h2>
              <ul className="edm-list">
                {d.sessions.map((s, k) => (
                  <li key={`${s.id}-${k}`}>
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.date ? fmtDate(s.date) : "Session"}
                    </a>
                    : {s.name}
                    {s.role || s.organisation ? `, ${[s.role, s.organisation].filter(Boolean).join(", ")}` : ""}
                    <span className="muted small">
                      {" "}
                      · {s.committees}
                      {s.inquiry_id && s.inquiry ? (
                        <>
                          {" · "}
                          <a href={`/inquiries/${s.inquiry_id}`}>{s.inquiry}</a>
                        </>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </>
  );
}

createRoot(document.getElementById("witnesses-root")!).render(
  <StrictMode>
    <Witnesses />
  </StrictMode>,
);
