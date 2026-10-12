import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, askBody, askStream } from "./api";
import { AnswerView } from "./components/AnswerView";
import { Controls } from "./components/Controls";
import { Login } from "./components/Login";
import { PlanChips } from "./components/PlanChips";
import { ElsewhereForSearch } from "./elsewhere";
import { EvidenceBar } from "./components/Evidence";
import { SourceDrawer, SourceList } from "./components/Sources";
import { SupportReminder } from "./components/SupportReminder";
import { TopicHeader } from "./components/TopicHeader";
import { ATTRIBUTION } from "./attribution";
import { BRAND } from "./brand";
import { Mark } from "./components/Mark";
import { fmtDate } from "./render";
import { SiteFooter } from "./components/SiteFooter";
import { COMPARE_HANDOVER, MORE, NAV } from "./nav";
import type { Answer, CompareSide, Evidence, Highlight, Meta, Plan, Settings, SourceCard, Turn } from "./types";

const SHARED = /^\/b\/([a-km-z2-9]{10})\/?$/;
const TOPIC = /^\/topics\/([a-z0-9-]+)\/?$/;

/**
 * Example questions, one set a day. Each set spans parties, both Houses, the nations and kinds of seat, and
 * party-specific examples use topics that party itself campaigns on, not other parties' attack lines.
 * Every question was checked to have plenty of balanced evidence in the record.
 */
export const EXAMPLE_SETS: string[][] = [
  [
    "How have ministers justified delays to HS2?",
    "What have peers said about assisted dying?",
    "How have Welsh MPs discussed steel jobs at Port Talbot?",
    "What have Liberal Democrat MPs said about sewage in rivers?",
  ],
  [
    "How have ministers explained NHS waiting lists?",
    "Where do rural and city MPs differ on onshore wind farms?",
    "What have Northern Ireland MPs said about the Windsor Framework?",
    "What have Conservative MPs said about defence spending?",
  ],
  [
    "What have MPs said about the Post Office Horizon IT system?",
    "What have select committee chairs said about water companies?",
    "What have SNP MPs said about the cost of living in Scotland?",
    "What have Reform UK MPs said about net zero?",
  ],
  [
    "What have Labour MPs said about workers' rights?",
    "What have peers said about the Rwanda asylum plan?",
    "What have Plaid Cymru MPs said about rural Wales?",
    "What have MPs for town seats said about high street closures?",
  ],
];

export function examplesFor(day: Date): string[] {
  return EXAMPLE_SETS[Math.floor(day.getTime() / 86_400_000) % EXAMPLE_SETS.length];
}

function loadSettings(defaults?: Meta["defaults"]): Settings {
  try {
    const saved = localStorage.getItem("hgpt.settings");
    if (saved) return JSON.parse(saved) as Settings;
  } catch {
    /* storage unavailable */
  }
  return {
    mode: "summary",
    recency: defaults?.recency ?? 0.5,
    roleWeight: defaults?.role_weight ?? 1.5,
    scope: { written: true, pbc: true, votes: true, edms: true, devolved: false, evidence: false },
  };
}

export default function App() {
  const [auth, setAuth] = useState<"unknown" | "in" | "out">("unknown");
  const [user, setUser] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [turns, setTurns] = useState<Turn[]>([]);
  // a question handed over from another page, such as an MP's page ("What has … said about …?")
  const [question, setQuestion] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get("q")?.slice(0, 500) ?? "";
    } catch {
      return "";
    }
  });
  // sides to compare, handed over from the Compare page (?compare=party:labour,party:conservative)
  const [compare, setCompare] = useState<CompareSide[]>(() => {
    try {
      const raw = new URLSearchParams(window.location.search).get("compare") ?? "";
      return raw
        .split(",")
        .map((x) => x.split(":"))
        .filter(([k, id]) => ["party", "person", "nation"].includes(k) && id)
        .slice(0, 3)
        .map(([k, id]) => ({ kind: k as CompareSide["kind"], id }));
    } catch {
      return [];
    }
  });
  const compareLabels = (() => {
    try {
      return (new URLSearchParams(window.location.search).get("sides") ?? "").split("|").filter(Boolean).slice(0, 3);
    } catch {
      return [];
    }
  })();
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const compareStarted = useRef(false);
  const [drawer, setDrawer] = useState<{ turn: string; h: Highlight } | null>(null);
  const [showControls, setShowControls] = useState(false);
  const [supportCount, setSupportCount] = useState(0); // > 0: show the note on what the site costs
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me.email);
      setAuth("in");
      const m = await api.meta();
      setMeta(m);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAuth("out");
      else setAuth("in");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void api.hit(window.location.pathname, document.referrer); // cookie-free page count
  }, [refresh]);

  // a topic address (/topics/<slug>) opens that topic's current briefing
  useEffect(() => {
    const m = window.location.pathname.match(TOPIC);
    if (!m) return;
    const slug = m[1];
    api
      .topic(slug)
      .then(({ topic, briefing: b, versions }) => {
        document.title = `${topic.title}: where MPs and peers stand — Where They Stand`;
        setTurns([
          b
            ? {
                id: b.id,
                question: b.question,
                settings,
                plan: b.plan ?? undefined,
                sources: b.sources,
                candidates: b.candidates,
                semantic: b.semantic,
                evidence: b.evidence,
                streamText: "",
                answer: b.answer,
                status: "done",
                briefingId: b.id,
                preparedAt: b.created_at,
                recordsUpTo: b.records_up_to,
                topic: { ...topic, versions },
              }
            : {
                id: slug,
                question: topic.question,
                settings,
                sources: [],
                streamText: "",
                status: "error",
                error: "This topic briefing has not been written yet. It will appear here after a coming update.",
                topic: { ...topic, versions },
              },
        ]);
      })
      .catch(() =>
        setTurns([
          {
            id: slug,
            question: "Topic not found",
            settings,
            sources: [],
            streamText: "",
            status: "error",
            error: "There is no topic at this address. The list of topics is at /topics.",
          },
        ]),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  // a shared address (/b/<id>) opens that briefing, exactly as it was prepared
  useEffect(() => {
    const m = window.location.pathname.match(SHARED);
    if (!m) return;
    const id = m[1];
    api
      .briefing(id)
      .then((b) =>
        setTurns([
          {
            id,
            question: b.question,
            settings,
            plan: b.plan ?? undefined,
            sources: b.sources,
            candidates: b.candidates,
            semantic: b.semantic,
            evidence: b.evidence,
            streamText: "",
            answer: b.answer,
            status: "done",
            briefingId: b.id,
            preparedAt: b.created_at,
            recordsUpTo: b.records_up_to,
            shared: true,
          },
        ]),
      )
      .catch((e: unknown) =>
        setTurns([
          {
            id,
            question: e instanceof ApiError && e.status === 410 ? "Briefing withdrawn" : "Briefing not found",
            settings,
            sources: [],
            streamText: "",
            status: "error",
            error:
              e instanceof ApiError && e.status === 410
                ? "This briefing has been withdrawn."
                : "There is no briefing at this address. It may have been mistyped.",
          },
        ]),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("hgpt.settings", JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings]);

  const update = (id: string, patch: Partial<Turn> | ((t: Turn) => Partial<Turn>)) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...(typeof patch === "function" ? patch(t) : patch) } : t)));

  const busy = turns.some((t) => !["done", "error"].includes(t.status));

  async function run(q: string, plan?: Plan, replaceId?: string, sourcesOnly = false) {
    const id = replaceId ?? crypto.randomUUID();
    const turn: Turn = { id, question: q, settings, sources: [], streamText: "", status: "planning", plan };
    setTurns((ts) => (replaceId ? ts.map((t) => (t.id === id ? turn : t)) : [...ts, turn]));
    const history = turns
      .filter((t) => t.id !== id && t.status === "done")
      .slice(-3)
      .map((t) => ({ question: t.question, answer: t.answer?.markdown?.slice(0, 600) ?? "" }));
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const sides = plan ? [] : compare;
      if (sides.length) {
        setCompare([]); // the comparison applies to the question it came with
        update(id, { comparing: compareLabels.length === sides.length ? compareLabels : [] });
      }
      for await (const ev of askStream(askBody(q, settings, plan, history, sourcesOnly, sides), ctrl.signal)) {
        if (ev.type === "plan") update(id, { plan: ev.plan as Plan, status: "searching" });
        else if (ev.type === "sources")
          update(id, {
            sources: ev.sources as SourceCard[],
            candidates: ev.candidates as number,
            semantic: ev.semantic as boolean,
            evidence: ev.evidence as Evidence,
            status: "answering",
          });
        else if (ev.type === "text") update(id, (t) => ({ streamText: t.streamText + (ev.text as string) }));
        else if (ev.type === "final")
          update(id, {
            answer: (ev.answer as Answer | null) ?? null,
            briefingKey: (ev.briefing_key as string | undefined) ?? undefined,
            briefingId: (ev.briefing_id as string | undefined) ?? undefined,
            preparedAt: (ev.prepared_at as string | undefined) ?? undefined,
            recordsUpTo: (ev.records_up_to as string | null | undefined) ?? undefined,
            note: ev.cached
              ? "This briefing was written earlier for the same question and settings, from the same data."
              : (ev.note as string | undefined),
            status: "done",
          });
        else if (ev.type === "error") update(id, { status: "error", error: ev.message as string });
        if (ev.type === "final" && typeof ev.support_reminder === "number") setSupportCount(ev.support_reminder);
        if (ev.type === "final" && typeof ev.briefing_id === "string") {
          // the address bar becomes this briefing's permanent link
          window.history.replaceState(null, "", `/b/${ev.briefing_id}`);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") update(id, { status: "error", error: (e as Error).message });
    }
  }

  function submit(e?: React.FormEvent, sourcesOnly = false) {
    e?.preventDefault();
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setQuestion("");
    void run(q, undefined, undefined, sourcesOnly);
  }

  // a comparison chosen on the Compare page starts at once. Only from there: a shared link with the same
  // parameters fills in the question but waits for Ask, so following a link never spends money by itself.
  useEffect(() => {
    if (compareStarted.current || auth !== "in" || !meta || compare.length < 2) return;
    let pending: string | null = null;
    try {
      pending = sessionStorage.getItem(COMPARE_HANDOVER);
      sessionStorage.removeItem(COMPARE_HANDOVER);
    } catch {
      pending = null;
    }
    const q = question.trim();
    if (!pending || pending !== q) return;
    compareStarted.current = true;
    setQuestion("");
    void run(q);
  }, [auth, meta, compare, question]); // eslint-disable-line react-hooks/exhaustive-deps

  if (auth === "unknown") return <div className="loading">Loading…</div>;
  if (auth === "out") return <Login onDone={() => void refresh()} />;

  const drawerTurn = drawer ? turns.find((t) => t.id === drawer.turn) : undefined;
  const drawerSource = drawerTurn?.sources.find((s) => s.n === drawer?.h.source) ?? null;

  const composer = (className: string) => (
    <form className={className} onSubmit={submit} role="search" aria-label="Ask a question">
      <label htmlFor="q" className="visually-hidden">
        Your question
      </label>
      <textarea
        id="q"
        value={question}
        placeholder="Ask a question about the proceedings of Parliament…"
        rows={2}
        ref={questionRef}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="composer-buttons">
        <button type="submit" className="primary" disabled={busy || question.trim().length < 3}>
          Ask
        </button>
        <button
          type="button"
          className="link small"
          disabled={busy || question.trim().length < 3}
          onClick={() => submit(undefined, true)}
          title="Find and show the sources without writing a briefing"
        >
          Sources only
        </button>
      </div>
    </form>
  );

  return (
    <div className={drawerSource ? "app with-drawer" : "app"}>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="masthead full-width">
        <p className="phase-banner">
          <strong className="phase-tag">Beta</strong>{" "}
          <span>
            This is a new service and it is still being tested. <a href="/corrections#report">Tell us about a problem</a>.
          </span>
        </p>
        <div className="running-head">
          <span>
            Parliament's record{meta ? ` since ${meta.archive_start.slice(0, 4)}` : ""}: debates, questions, statements,
            votes, bills, committees and members' interests
          </span>
          <span className="masthead-actions">
            <nav className="page-nav" aria-label="Site">
              {NAV.map((n) => (
                <a key={n.href} href={n.href} aria-current={n.href === "/" ? "page" : undefined}>
                  {n.label}
                </a>
              ))}
              <details className="nav-more">
                <summary>More</summary>
                <div className="nav-more-list">
                  {MORE.map((n) => (
                    <a key={n.href} href={n.href}>
                      {n.label}
                    </a>
                  ))}
                </div>
              </details>
            </nav>
            <button type="button" className="secondary" onClick={() => setShowControls(!showControls)} aria-expanded={showControls}>
              Settings
            </button>
            {user && (
              <button type="button" className="link" onClick={() => void api.logout().then(() => setAuth("out"))}>
                Sign out
              </button>
            )}
          </span>
        </div>
        <div className="title-block">
          <Mark />
          <h1 className="wordmark">{BRAND.name}</h1>
          <p className="tagline">{BRAND.tagline}</p>
          <p className="imprint">
            <span>Independent research service</span>
            <span>Every statement cited</span>
            {meta?.last_sync?.finished_at && <span>Updated {fmtDate(meta.last_sync.finished_at.slice(0, 10))}</span>}
          </p>
        </div>
      </header>

      {supportCount > 0 && meta?.donate_url && (
        <SupportReminder count={supportCount} donateUrl={meta.donate_url} onClose={() => setSupportCount(0)} />
      )}
      {compare.length > 0 && (
        <aside className="banner" aria-label="Comparison">
          Comparing {compareLabels.length === compare.length ? compareLabels.join(" and ") : "the chosen sides"}: each is
          searched separately and given an equal share of the sources.{" "}
          <button type="button" className="link" onClick={() => setCompare([])}>
            Cancel the comparison
          </button>
        </aside>
      )}
      {showControls && (
        <Controls settings={settings} onChange={setSettings} answersEnabled={meta?.answers_enabled ?? true} />
      )}
      {meta && !meta.answers_enabled && (
        <aside className="banner" aria-label="Service notice">
          Briefings need an Anthropic API key on the server. Until one is set you will see the balanced evidence set only.
        </aside>
      )}

      <main className="thread" id="main" tabIndex={-1}>
        {turns.length === 0 && (
          <section className="empty">
            <h2>
              Ask about the record of Parliament <span className="ai-tag">AI-powered</span>
            </h2>
            <p>
              Ask a question in your own words. Unlike Hansard's search, it does not just match the exact words you
              type: it works out what you are asking about and finds the MPs and peers who spoke on it, even when they
              put it differently. Then AI (Claude) pulls the speeches, answers, statements and votes since 1997 into
              one short briefing, so you do not have to read through results date by date: who said what, and where
              they stand, with every statement cited to the exact words in Hansard.
            </p>
            {composer("composer composer-inline")}
            <p className="ai-caution">
              AI can make mistakes: check the cited sources before relying on a briefing. Prefer no AI? Choose
              &ldquo;Sources only&rdquo; to see the most relevant records without a written briefing, or use{" "}
              <a href="https://hansard.parliament.uk/search" target="_blank" rel="noreferrer">
                Hansard's own search
              </a>{" "}
              to find every mention of a word. The <a href="/resources">other resources</a> page lists more sites
              worth using alongside this one.
            </p>
            <h3 className="examples-head">Example questions</h3>
            <ol className="examples">
              {examplesFor(new Date()).map((ex) => (
                <li key={ex}>
                  <button type="button" className="example" onClick={() => {
                      setQuestion(ex);
                      questionRef.current?.focus();
                    }}>
                    {ex}
                  </button>
                </li>
              ))}
            </ol>
            <h3 className="examples-head">How this differs from a search</h3>
            <ul className="ask-why">
              <li>
                <strong>Answers, not a list of hits.</strong> Hansard's own search and TheyWorkForYou list every
                mention of the words you type, in date order, for you to read through. Here the contributions that
                answer your question are found by meaning and brought together in one briefing.
              </li>
              <li>
                <strong>Balanced by design.</strong> Each briefing draws on ministers and the opposition, backbenchers
                and peers, across parties and parts of the country, and shows that spread. It takes no view of its
                own.
              </li>
              <li>
                <strong>Checkable.</strong> Every statement links to the record it comes from, with the speaker's
                party, seat and role on the day. Statements the record does not support are removed.
              </li>
            </ul>
          </section>
        )}
        {turns.map((t) => (
          <article key={t.id} className="turn">
            {t.topic && <TopicHeader topic={t.topic} preparedAt={t.preparedAt} recordsUpTo={t.recordsUpTo} />}
            {t.comparing !== undefined && (
              <p className="eyebrow">
                Comparison{t.comparing.length ? `: ${t.comparing.join(" and ")}` : ""} ·{" "}
                <a href="/compare">Compare something else</a>
              </p>
            )}
            <h2 className="question">{t.question}</h2>
            {t.shared && t.preparedAt && (
              <p className="shared-note">
                A saved briefing, prepared {fmtDate(t.preparedAt.slice(0, 10))}. The record may have changed since.{" "}
                <button type="button" className="link" disabled={busy} onClick={() => void run(t.question)}>
                  Ask again for an up-to-date briefing
                </button>
              </p>
            )}
            {t.plan && <PlanChips key={JSON.stringify(t.plan)} plan={t.plan} meta={meta} busy={busy} onRerun={(p) => void run(t.question, p, t.id)} />}
            <EvidenceBar
              evidence={t.evidence}
              demographics={
                !!t.plan &&
                (["gender", "age"].includes(t.plan.group_by ?? "role") ||
                  !!t.plan.filters.genders?.length ||
                  !!t.plan.filters.age_bands?.length)
              }
              seats={
                !!t.plan &&
                (["tenure", "majority"].includes(t.plan.group_by ?? "role") ||
                  !!t.plan.filters.tenure?.length ||
                  !!t.plan.filters.majority_bands?.length)
              }
            />
            {t.status === "planning" && <p className="status" role="status">Interpreting the question…</p>}
            {t.status === "done" && (
              <p className="visually-hidden" role="status">
                {t.answer ? "Briefing ready." : "Sources ready."}
              </p>
            )}
            {t.status === "searching" && <p className="status" role="status">Searching the Official Report…</p>}
            {t.status === "answering" && !t.streamText && t.sources.length > 0 && (
              <p className="status" role="status">Preparing a sourced briefing from {t.sources.length} contributions…</p>
            )}
            {(t.streamText || t.answer) && (
              <AnswerView
                question={t.question}
                answer={t.answer}
                streamText={t.streamText}
                sources={t.sources}
                briefingKey={t.briefingKey}
                briefingId={t.briefingId}
                preparedAt={t.preparedAt}
                recordsUpTo={t.recordsUpTo}
                onCite={(h) => setDrawer({ turn: t.id, h })}
              />
            )}
            {t.note && <p className="muted small">{t.note}</p>}
            {t.status === "error" && (
              <p className="error" role="alert">
                {t.error}
              </p>
            )}
            <SourceList
              sources={t.sources}
              onOpen={(h) => setDrawer({ turn: t.id, h })}
              open={t.status === "answering" || (!t.answer && t.status === "done")}
              writing={t.status === "answering"}
            />
            {t.status === "done" && t.plan && (
              <ElsewhereForSearch
                words={t.plan.search_text}
                from={t.plan.filters.date_from}
                to={t.plan.filters.date_to}
                noRecords={!!t.answer?.no_records || t.sources.length === 0}
              />
            )}
            {t.status === "done" && t.semantic === false && (
              <p className="muted small">Meaning-based search is still being built; these results used keyword search.</p>
            )}
          </article>
        ))}
      </main>

      {turns.length > 0 && composer("composer")}

      <SourceDrawer source={drawerSource} quotes={drawer?.h.quotes ?? []} onClose={() => setDrawer(null)} />

      <SiteFooter donateUrl={meta?.donate_url} attribution={meta?.attribution ?? ATTRIBUTION}>
        <p className="print-only">
          From {BRAND.name} (beta), wheretheystand.uk. Briefings are written by AI from the cited Hansard records; check the
          sources.
        </p>
      </SiteFooter>
    </div>
  );
}
