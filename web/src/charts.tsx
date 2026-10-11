/** The charts page: words in, a chart of how often they were used each year, with the context to read it. */
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./pages";
import { LineChart } from "./components/LineChart";

interface ApiSeries {
  key: string;
  phrase: string;
  group: string;
  label: string;
  counts: number[];
  totals: number[];
  rate: (number | null)[];
}
interface ChartData {
  phrases: string[];
  by: string;
  years: number[];
  series: ApiSeries[];
  partial_years: number[];
  total: number;
}

const BY: [string, string][] = [
  ["all", "No split"],
  ["party", "By party"],
  ["house", "Commons and Lords"],
  ["nation", "By nation"],
];
const EXAMPLES = ["food banks", "artificial intelligence", "onshore wind", "cost of living, energy bills"];

function Charts() {
  const params = new URLSearchParams(window.location.search);
  const [words, setWords] = useState(params.get("q") ?? "");
  const [by, setBy] = useState(params.get("by") ?? "all");
  const [mode, setMode] = useState<"rate" | "count">("rate");
  const [query, setQuery] = useState<{ q: string; by: string } | null>(
    params.get("q") ? { q: params.get("q")!, by: params.get("by") ?? "all" } : null,
  );
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query) return;
    setData(null);
    setError(null);
    window.history.replaceState(null, "", `/charts?q=${encodeURIComponent(query.q)}&by=${query.by}`);
    fetch(`/api/trends?q=${encodeURIComponent(query.q)}&by=${query.by}`)
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The chart could not be drawn.");
        setData(body as ChartData);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "The chart could not be drawn."));
  }, [query]);

  const several = words.includes(",");
  const unit = mode === "rate" ? "per 10,000 contributions" : "contributions";
  const first = data?.phrases[0] ?? "";
  return (
    <>
      <form
        className="ask-about"
        onSubmit={(e) => {
          e.preventDefault();
          if (words.trim()) setQuery({ q: words.trim(), by: several ? "all" : by });
        }}
      >
        <label htmlFor="words">Words or a phrase</label>
        <div className="ask-row">
          <input id="words" value={words} onChange={(e) => setWords(e.target.value)} placeholder="for example food banks" required />
          <button type="submit" className="primary" disabled={!words.trim()}>
            Draw chart
          </button>
        </div>
        <p className="muted small">To compare up to three, separate them with commas: cost of living, energy bills.</p>
        <fieldset className="chart-options" disabled={several}>
          <legend>Split the count</legend>
          {BY.map(([k, label]) => (
            <label key={k}>
              <input type="radio" name="by" value={k} checked={by === k} onChange={() => setBy(k)} /> {label}
            </label>
          ))}
        </fieldset>
      </form>

      {!query && (
        <p>
          Try:{" "}
          {EXAMPLES.map((ex, i) => (
            <span key={ex}>
              {i > 0 && ", "}
              <button type="button" className="link" onClick={() => { setWords(ex); setQuery({ q: ex, by: "all" }); }}>
                {ex}
              </button>
            </span>
          ))}
          .
        </p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      {query && !data && !error && <p className="muted" role="status">Counting… this can take a few seconds.</p>}
      {data && data.series.length === 0 && <p>These words do not appear in the record since 2010. Try other words.</p>}
      {data && data.series.length > 0 && (
        <section aria-labelledby="h-chart">
          <h2 id="h-chart">
            {data.phrases.map((p) => `“${p}”`).join(", ")}: {data.total.toLocaleString("en-GB")} contributions
          </h2>
          <fieldset className="chart-options">
            <legend>Show</legend>
            <label>
              <input type="radio" name="mode" checked={mode === "rate"} onChange={() => setMode("rate")} /> Per 10,000
              contributions (recommended)
            </label>
            <label>
              <input type="radio" name="mode" checked={mode === "count"} onChange={() => setMode("count")} /> Number of
              contributions
            </label>
          </fieldset>
          <LineChart
            years={data.years}
            partial={data.partial_years}
            unit={unit}
            title={`${data.phrases.join(", ")}: ${unit}, by year`}
            series={data.series.map((s) => ({
              key: s.key,
              group: s.group,
              label: s.label,
              values: mode === "rate" ? s.rate : s.counts,
            }))}
          />
          <div className="chart-context">
            <h3>Reading this chart</h3>
            <ul>
              <li>
                Each count is a contribution (a speech, question, answer or statement) that contains these exact words.
                It says nothing about what was said: <a href={`/?q=${encodeURIComponent(`What has been said about ${first}?`)}`}>ask
                a question</a> or look at a <a href="/timeline">timeline</a> to see that.
              </li>
              <li>
                “Per 10,000” compares the count with all contributions by the same group that year. It allows for busy
                and quiet years (elections, long recesses) and for the size of each party, so a bigger party does not
                look keener just because it says more.
              </li>
              <li>
                Rises often follow a bill, an event or a debate on a single day; a small group's rate can jump on a
                handful of contributions, so check the numbers in the table.
              </li>
              <li>2010 starts in May, at the general election, and the current year is not yet over.</li>
              {data.by === "nation" && <li>Nations are those of MPs' seats; members of the Lords have none and are shown separately.</li>}
              {data.by === "party" && <li>Party is the member's party on the day. Labour includes Labour/Co-operative members.</li>}
            </ul>
          </div>
          <details className="chart-table">
            <summary>Show the numbers</summary>
            <div className="table-wrap">
              <table className="admin-table">
                <caption className="visually-hidden">Contributions by year</caption>
                <thead>
                  <tr>
                    <th scope="col">Year</th>
                    {data.series.map((s) => (
                      <th key={s.key} scope="col">
                        {s.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.years.map((yr, i) => (
                    <tr key={yr}>
                      <th scope="row">{data.partial_years.includes(yr) ? `${yr} (part)` : yr}</th>
                      {data.series.map((s) => (
                        <td key={s.key}>
                          {s.counts[i].toLocaleString("en-GB")} of {s.totals[i].toLocaleString("en-GB")}
                          {s.rate[i] != null && <span className="muted"> ({s.rate[i]} per 10,000)</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
    </>
  );
}

createRoot(document.getElementById("charts-root")!).render(
  <StrictMode>
    <Charts />
  </StrictMode>,
);
