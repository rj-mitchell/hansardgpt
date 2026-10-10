import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, askBody, askStream } from "./api";
import { AnswerView } from "./components/AnswerView";
import { Controls } from "./components/Controls";
import { Login } from "./components/Login";
import { PlanChips } from "./components/PlanChips";
import { EvidenceBar } from "./components/Evidence";
import { SourceDrawer, SourceList } from "./components/Sources";
import { ATTRIBUTION } from "./attribution";
import { BRAND } from "./brand";
import { Mark } from "./components/Mark";
import { fmtDate } from "./render";
import type { Answer, Evidence, Highlight, Meta, Plan, Settings, SourceCard, Turn } from "./types";

const EXAMPLES = [
  { q: "What have northern Labour MPs said about HS2?", house: "commons" },
  { q: "Where do rural and city MPs differ on onshore wind farms?", house: "gilt" },
  { q: "What have peers said about assisted dying?", house: "lords" },
  { q: "How have ministers justified delays to HS2?", house: "commons" },
];

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
    scope: { written: true, pbc: true, votes: true },
  };
}

export default function App() {
  const [auth, setAuth] = useState<"unknown" | "in" | "out">("unknown");
  const [user, setUser] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [drawer, setDrawer] = useState<{ turn: string; h: Highlight } | null>(null);
  const [showControls, setShowControls] = useState(false);
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
  }, [refresh]);

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

  async function run(q: string, plan?: Plan, replaceId?: string) {
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
      for await (const ev of askStream(askBody(q, settings, plan, history), ctrl.signal)) {
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
            note: ev.cached
              ? "This briefing was written earlier for the same question and settings, from the same data."
              : (ev.note as string | undefined),
            status: "done",
          });
        else if (ev.type === "error") update(id, { status: "error", error: ev.message as string });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") update(id, { status: "error", error: (e as Error).message });
    }
  }

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setQuestion("");
    void run(q);
  }

  if (auth === "unknown") return <div className="loading">Loading…</div>;
  if (auth === "out") return <Login onDone={() => void refresh()} />;

  const drawerTurn = drawer ? turns.find((t) => t.id === drawer.turn) : undefined;
  const drawerSource = drawerTurn?.sources.find((s) => s.n === drawer?.h.source) ?? null;

  return (
    <div className={drawerSource ? "app with-drawer" : "app"}>
      <header className="masthead full-width">
        <div className="running-head">
          <span>
            Debates, written answers and votes{meta ? `, ${meta.archive_start.slice(0, 4)} to date` : ""}
          </span>
          <span className="masthead-actions">
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
        <h1 className="wordmark">
          <Mark />
          <span className="wordmark-text">
            Hansard <em>Guru</em>
          </span>
        </h1>
        <p className="tagline">
          {BRAND.tagline}
          {meta?.last_sync?.finished_at ? ` · updated ${fmtDate(meta.last_sync.finished_at.slice(0, 10))}` : ""}
        </p>
        <p className="stamp">Independent · every claim sourced</p>
      </header>

      {showControls && (
        <Controls settings={settings} onChange={setSettings} answersEnabled={meta?.answers_enabled ?? true} />
      )}
      {meta && !meta.answers_enabled && (
        <p className="banner">
          Briefings need an Anthropic API key on the server. Until one is set you will see the balanced evidence set only.
        </p>
      )}

      <main className="thread" aria-live="polite">
        {turns.length === 0 && (
          <section className="empty">
            <h2>What has Parliament said about…?</h2>
            <p>
              Ask a question and the Guru reads Hansard for you, then writes a short briefing on where ministers, the
              opposition, city, town and rural MPs, and peers stand. It has no opinions of its own: every point links
              to the speech it came from, with the speaker's role on that date and the official reference.
            </p>
            <p className="muted small">
              Looking for every mention of a word?{" "}
              <a href="https://hansard.parliament.uk/search" target="_blank" rel="noreferrer">
                Hansard's own search
              </a>{" "}
              does that best.
            </p>
            <h3 className="examples-head">Try one of these</h3>
            <ul className="examples">
              {EXAMPLES.map((ex) => (
                <li key={ex.q} data-house={ex.house}>
                  <button type="button" className="example" onClick={() => setQuestion(ex.q)}>
                    {ex.q}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {turns.map((t) => (
          <article key={t.id} className="turn">
            <h2 className="question">{t.question}</h2>
            {t.plan && <PlanChips key={JSON.stringify(t.plan)} plan={t.plan} meta={meta} busy={busy} onRerun={(p) => void run(t.question, p, t.id)} />}
            <EvidenceBar evidence={t.evidence} />
            {t.status === "planning" && <p className="status">Reading your question…</p>}
            {t.status === "searching" && <p className="status">Leafing through Hansard…</p>}
            {t.status === "answering" && !t.streamText && t.sources.length > 0 && (
              <p className="status">Writing a sourced briefing from {t.sources.length} contributions…</p>
            )}
            {(t.streamText || t.answer) && (
              <AnswerView answer={t.answer} streamText={t.streamText} onCite={(h) => setDrawer({ turn: t.id, h })} />
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
              open={!t.answer && t.status === "done"}
            />
            {t.status === "done" && t.semantic === false && (
              <p className="muted small">Meaning-based search is still being built; these results used keyword search.</p>
            )}
          </article>
        ))}
      </main>

      <form className="composer" onSubmit={submit}>
        <label htmlFor="q" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="q"
          value={question}
          placeholder="Ask about anything debated in Parliament…"
          rows={2}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="submit" className="primary" disabled={busy || question.trim().length < 3}>
          Ask
        </button>
      </form>

      <SourceDrawer source={drawerSource} quotes={drawer?.h.quotes ?? []} onClose={() => setDrawer(null)} />

      <footer className="footer full-width">
        <p className="independence">{BRAND.independence}</p>
        {(meta?.attribution ?? ATTRIBUTION).map((a) => (
          <a key={a.url} href={a.url} target="_blank" rel="noreferrer">
            {a.text}
          </a>
        ))}
      </footer>
    </div>
  );
}
