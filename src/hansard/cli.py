"""``hansard`` command-line interface."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import typer

from hansard.config import STATIC_DIR, Settings, load_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Where They Stand: sourced briefings on the record of the UK Parliament.")
user_app = typer.Typer(no_args_is_help=True, help="Manage invite-only user accounts.")
app.add_typer(user_app, name="user")
topics_app = typer.Typer(no_args_is_help=True, help="Topic briefings (config/topics.toml).")
app.add_typer(topics_app, name="topics")
eval_app = typer.Typer(no_args_is_help=True, help="Score the site against the test set (eval/questions.toml).")
app.add_typer(eval_app, name="eval")

log = logging.getLogger("hansard")


def _settings() -> Settings:
    return load_settings()


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


# --------------------------------------------------------------------------- reference


def build_reference_data(settings: Settings, pull: bool = True, members_dir: Path | None = None) -> dict:
    from hansard.reference.build import build_reference
    from hansard.sources import parlparse
    from hansard.store.state import StateDB
    from hansard.sync import install_reference, refresh_demographics_data, refresh_elections_data

    state = StateDB(settings.state_db)
    sha = None
    live = members_dir is None  # the real member data (not the sample fixtures): fetch the extras too
    demographics, demo_status = refresh_demographics_data(settings, fetch=live)
    if members_dir is None:
        if pull:
            sha = parlparse.ensure_checkout(settings.sources["parlparse_repo"], settings.parlparse_dir,
                                            settings.sources.get("parlparse_branch", "master"))
        else:
            sha = parlparse.head_sha(settings.parlparse_dir)
        members_dir = parlparse.members_dir(settings.parlparse_dir)
    elections, elec_status = refresh_elections_data(settings, members_dir, fetch=live)
    ref = build_reference(members_dir, STATIC_DIR / "geo" / "constituencies.csv",
                          Path(settings.config_path).parent / "overrides" / "constituency_names.csv",
                          demographics, elections)
    people = install_reference(settings, state, ref, sha)
    # the index's speaker columns for these people are refreshed by the next `hansard sync`
    return {**ref.stats, "parlparse_sha": sha, "people_changed": len(people), "demographics": demo_status,
            "elections": elec_status}


@app.command()
def reference(pull: bool = typer.Option(True, help="git pull parlparse members/ first"),
              members: Path = typer.Option(None, help="use this members/ directory instead of the checkout")):
    """Build reference tables (people, seats, offices, regions) from parlparse."""
    _setup_logging()
    stats = build_reference_data(_settings(), pull=pull, members_dir=members)
    unmatched = stats.pop("unmatched_seats_since_2010")
    typer.echo(json.dumps(stats, indent=2, default=str))
    if unmatched:
        typer.echo(f"WARNING: {len(unmatched)} seats since 2010 without an ONS match: {unmatched[:10]}")


# --------------------------------------------------------------------------- data


@app.command()
def fetch(since: str = typer.Option(None, help="first date (default: archive start)"),
          transport: str = typer.Option("auto", help="auto | rsync | https")):
    """Mirror new and corrected scrapedxml files from TheyWorkForYou."""
    _setup_logging()
    typer.echo(json.dumps(fetch_xml(_settings(), _date(since), transport), indent=2))


def fetch_xml(settings: Settings, since: date | None = None, transport: str = "auto") -> dict:
    from hansard.ingest import DIVISION_DIRS
    from hansard.sources.twfy import HttpsMirror, rsync_available, rsync_directories

    since = since or settings.archive_start
    dirs = [*settings.record_dirs, *sorted(DIVISION_DIRS)]
    src = settings.sources
    if transport in ("auto", "rsync") and rsync_available(src["twfy_rsync"]):
        rsync_directories(src["twfy_rsync"], settings.raw_xml_dir, dirs, since.year)
        return {"transport": "rsync"}
    if transport == "rsync":
        raise typer.Exit("rsync to TheyWorkForYou is not reachable")
    mirror = HttpsMirror(src["twfy_https"], settings.raw_xml_dir)
    plan = mirror.plan(dirs, since)
    done = mirror.download(plan)
    return {"transport": "https", "planned": len(plan), "downloaded": len(done)}


@app.command()
def ingest(workers: int = typer.Option(3, help="parser processes (each streams one file)"),
           since: str = typer.Option(None), until: str = typer.Option(None)):
    """Parse new or corrected XML files into the Parquet store."""
    _setup_logging()
    from hansard.ingest import ingest as run

    stats = run(_settings(), workers=workers, since=_date(since), until=_date(until))
    typer.echo(json.dumps(stats.as_dict(), indent=2, default=str))


@app.command()
def index(rebuild_fts: bool = typer.Option(True, help="(re)build the BM25 index afterwards"),
          dedupe: bool = typer.Option(False, help="one-off: drop older copies of republished "
                                                  "records left by earlier versions of the indexer")):
    """Add newly ingested records to the keyword search index."""
    _setup_logging()
    settings = _settings()
    typer.echo(json.dumps(index_pending(settings, rebuild_fts, dedupe), indent=2))


def index_pending(settings: Settings, rebuild_fts: bool = True, dedupe: bool = False) -> dict:
    from hansard.index.build import Indexer
    from hansard.index.lance import SearchIndex
    from hansard.store.state import StateDB

    idx = SearchIndex(settings.index_dir, int(settings.embedding.get("dim", 384)))
    t = time.time()
    indexer = Indexer(settings, idx, StateDB(settings.state_db))
    out = indexer.dedupe() if dedupe else {}
    n = indexer.index_pending()
    if rebuild_fts and (n or dedupe):
        idx.build_indices()
    elif n:
        idx.optimize()
    return {"passages_written": n, **out, "seconds": round(time.time() - t, 1), **idx.stats()}


@app.command()
def embed(max_files: int = typer.Option(None, help="stop after this many files"),
          max_minutes: float = typer.Option(None, help="stop after this many minutes (resumable)")):
    """Embed passages for semantic search, newest first (resumable)."""
    _setup_logging()
    settings = _settings()
    typer.echo(json.dumps(embed_pending_cmd(settings, max_files, max_minutes), indent=2))


def embed_pending_cmd(settings: Settings, max_files=None, max_minutes=None) -> dict:
    from hansard.embed.base import get_embedder, model_fingerprint
    from hansard.index.build import embed_pending
    from hansard.index.lance import SearchIndex
    from hansard.store.state import StateDB

    state = StateDB(settings.state_db)
    idx = SearchIndex(settings.index_dir, int(settings.embedding.get("dim", 384)))
    embedder = get_embedder(settings)
    if settings.embedding.get("backend") == "fastembed":
        fp = model_fingerprint(settings.data_dir / "models")
        prev = state.get("embedding_model_sha256")
        if prev and prev != fp:
            raise typer.Exit("embedding model weights changed since the index was built; "
                             "rebuild vectors or restore the pinned model")
        state.set("embedding_model_sha256", fp)
        state.set("embedding_model", embedder.name)
    t = time.time()
    n = embed_pending(settings, idx, state, embedder, max_files=max_files,
                      max_seconds=max_minutes * 60 if max_minutes else None)
    if n and idx.stats()["vectors"] >= 10_000:
        idx.build_indices()
    return {"passages_embedded": n, "seconds": round(time.time() - t, 1), **idx.stats()}


@app.command()
def status():
    """Show data, index and sync status."""
    from hansard.index.lance import SearchIndex
    from hansard.store.state import StateDB

    settings = _settings()
    state = StateDB(settings.state_db)
    manifest = state.manifest()
    idx = SearchIndex(settings.index_dir, int(settings.embedding.get("dim", 384)))
    out = {
        "data_dir": str(settings.data_dir),
        "files_ingested": len(manifest),
        "files_unindexed": len(state.unindexed()),
        "files_unembedded": len(state.unembedded()),
        "index": idx.stats(),
        "parlparse_sha": state.get("parlparse_sha"),
        "embedding_model": state.get("embedding_model"),
        "last_runs": state.runs(5),
    }
    typer.echo(json.dumps(out, indent=2, default=str))


# --------------------------------------------------------------------------- search


@app.command()
def search(query: str, date_from: str = typer.Option(None, "--from"), date_to: str = typer.Option(None, "--to"),
           region: list[str] = typer.Option(None), house: list[str] = typer.Option(None),
           portfolio: list[str] = typer.Option(None), office: list[str] = typer.Option(None),
           recency: float = typer.Option(None), role_weight: float = typer.Option(None),
           limit: int = typer.Option(10), no_written: bool = typer.Option(False)):
    """Run the deterministic retrieval pipeline and print ranked sources."""
    from hansard.engine import Engine, Filters, Scope

    settings = _settings()
    t = time.time()
    eng = Engine(settings)
    res = eng.search(query, Filters(date_from=_date(date_from), date_to=_date(date_to), regions=region or [],
                                    houses=house or [], offices=office or []),
                     Scope(written=not no_written), portfolio or [], recency, role_weight, limit)
    typer.echo(f"{res.candidates} candidates, semantic={'on' if res.semantic_available else 'off'}, "
               f"{time.time() - t:.2f}s")
    for i, r in enumerate(res.records, 1):
        sp = r["speaker"] or {}
        offices = "; ".join(o["title"] for o in sp.get("offices", [])) or "backbench"
        typer.echo(f"\n[{i}] {r['date']} {r['chamber']} col {r['colnum'] or r['uin'] or '-'} | "
                   f"{sp.get('name') or r['speaker_name_raw']} ({sp.get('party')}, {sp.get('constituency') or sp.get('house')})"
                   f" | {offices}\n    {r['heading']}\n    {r['excerpt'][:300]}...\n    {r['ranking']}")


# --------------------------------------------------------------------------- sync and bootstrap


@app.command()
def sync(embed_minutes: float = typer.Option(60.0, help="time budget for embedding new passages"),
         fetch_data: bool = typer.Option(True, "--fetch/--no-fetch")):
    """Daily incremental update: member data, new Hansard, index, embeddings."""
    _setup_logging()
    from hansard.sync import run_sync

    stats = run_sync(_settings(), fetch=fetch_data, embed_minutes=embed_minutes)
    typer.echo(json.dumps(stats, indent=2, default=str))
    if stats.get("error"):
        raise typer.Exit(1)


@app.command()
def bootstrap(sample: bool = typer.Option(False, help="offline demo using bundled fixtures"),
              since: str = typer.Option(None, "--from", help="first date to load (default: archive start)"),
              embed_minutes: float = typer.Option(None, help="limit initial embedding time (resumable later)"),
              keyword_only: bool = typer.Option(False, help="skip meaning-based search (smaller server; remembered)"),
              workers: int = typer.Option(3)):
    """One-command setup: reference data, Hansard download, ingest, index, embeddings, smoke test."""
    _setup_logging()
    from hansard.bootstrap import run_bootstrap

    stats = run_bootstrap(_settings(), sample=sample, since=_date(since), embed_minutes=embed_minutes,
                          workers=workers, keyword_only=keyword_only)
    typer.echo(json.dumps(stats, indent=2, default=str))


# --------------------------------------------------------------------------- web


@app.command("set-key")
def set_key(key: str = typer.Option(..., prompt="Paste your Anthropic API key (it will not be shown)",
                                    hide_input=True)):
    """Save the Anthropic API key in the data folder (handy when running on your own computer)."""
    import os

    from hansard.rag.answer import KEY_FILE, make_client

    key = key.strip()
    if not key.startswith("sk-ant-"):
        raise typer.BadParameter("that doesn't look like an Anthropic API key (they start with sk-ant-)")
    path = _settings().data_dir / KEY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)
    typer.echo(f"Saved ({len(key)} characters). Checking it with Anthropic...")
    import anthropic

    try:
        os.environ["HANSARD_ANTHROPIC_API_KEY"] = key
        make_client().models.list(limit=1)
    except anthropic.AuthenticationError:
        path.unlink()
        typer.echo("Anthropic did not accept that key, so it was not kept. Check it and run this again.")
        raise typer.Exit(1) from None
    except Exception as e:  # noqa: BLE001 - network trouble etc.: keep the key, say what happened
        typer.echo(f"Kept the key, but could not check it just now ({type(e).__name__}).")
        return
    typer.echo("The key works. Written briefings are switched on.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False,
          behind_proxy: bool = typer.Option(False, help="trust X-Forwarded-* headers (e.g. behind Caddy)"),
          access_log: bool = typer.Option(False, help="log every request, with visitors' IP addresses (off by "
                                                      "default: the site keeps its own cookie-free counts)")):
    """Run the web application."""
    import uvicorn

    _setup_logging()
    uvicorn.run("hansard.api.app:create_app", host=host, port=port, factory=True, reload=reload,
                proxy_headers=behind_proxy, forwarded_allow_ips="*" if behind_proxy else None,
                access_log=access_log)


@app.command()
def backup(to: Path = typer.Option(None, help="folder for backups (default: <data>/backups)"),
           keep: int = typer.Option(14, help="how many daily backups to keep")):
    """Back up what cannot be rebuilt: saved briefings, reports, feedback, usage and visit counts."""
    from hansard.backup import make_backup

    _setup_logging()
    typer.echo(f"Backed up to {make_backup(_settings(), to, keep)}")


@app.command()
def restore(archive: Path = typer.Argument(..., exists=True, dir_okay=False),
            yes: bool = typer.Option(False, "--yes", help="do not ask for confirmation")):
    """Put a backup back (stop the site first). Replaces the current saved briefings, reports and usage."""
    from hansard.backup import restore_backup

    if not yes:
        typer.confirm("This replaces the current saved briefings, reports and usage records. Continue?", abort=True)
    restore_backup(_settings(), archive)
    typer.echo("Restored. Start the site again.")


@user_app.command("add")
def user_add(email: str, admin: bool = typer.Option(False),
             password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True)):
    """Invite a user (create an account)."""
    from hansard.api.auth import create_user
    from hansard.store.state import StateDB

    create_user(StateDB(_settings().state_db), email, password, admin)
    typer.echo(f"created {email}")


@user_app.command("list")
def user_list():
    from hansard.store.state import StateDB

    with StateDB(_settings().state_db).connect() as con:
        for r in con.execute("SELECT email, is_admin, disabled, created_at FROM users ORDER BY email"):
            typer.echo(f"{r[0]}  admin={bool(r[1])}  disabled={bool(r[2])}  since {r[3]}")


@user_app.command("disable")
def user_disable(email: str):
    from hansard.store.state import StateDB

    with StateDB(_settings().state_db).connect() as con:
        con.execute("UPDATE users SET disabled = 1 WHERE email = ?", (email,))
        con.execute("DELETE FROM sessions WHERE user_id IN (SELECT user_id FROM users WHERE email = ?)", (email,))
    typer.echo(f"disabled {email}")


# ---- topic briefings ----------------------------------------------------------------------------------------------


@topics_app.command("list")
def topics_list():
    """Each topic, its current version and when it was last checked."""
    from hansard.store.state import StateDB
    from hansard.topics import topic_listing

    for t in topic_listing(_settings(), StateDB(_settings().state_db)):
        cur = t["current"]
        chk = t["last_check"]
        typer.echo(f"{t['slug']:32} {('written ' + cur['prepared_at'][:10]) if cur else 'not written yet':22} "
                   f"{t['versions']} version(s)  {('last check: ' + chk['outcome']) if chk else ''}")


@topics_app.command("refresh")
def topics_refresh(only: list[str] = typer.Option(None, help="just these topics (slugs)"),
                   force: bool = typer.Option(False, help="rewrite even if not due or the evidence is unchanged"),
                   limit: int = typer.Option(None, help="at most this many rewrites (default: max_per_run)")):
    """Rewrite the topic briefings that are due. Each rewrite costs about 11p."""
    from hansard.rag.pipeline import Pipeline
    from hansard.store.state import StateDB
    from hansard.topics import refresh_topics

    settings = _settings()
    _setup_logging()
    res = refresh_topics(settings, StateDB(settings.state_db), Pipeline(settings), only=only or None, force=force,
                         limit=limit, progress=typer.echo)
    typer.echo(f"{sum(1 for r in res if r['outcome'].startswith('rewritten'))} rewritten")


# ---- the test set ------------------------------------------------------------------------------------------------

EVAL_DIR = Path("eval")


def _eval_setup(questions: Path, only: str | None):
    from hansard.evaluate import load_questions

    today, qs = load_questions(questions)
    if only:
        keep = set(only.split(","))
        qs = [q for q in qs if q.id in keep]
    return today, qs


def _client():
    from hansard.rag.answer import make_client

    return make_client()


def _load_plans(path: Path) -> dict[str, dict]:
    run = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r["plan"] for r in run["rows"] if r.get("plan")}


@eval_app.command("plans")
def eval_plans(model: str = typer.Option(None, help="model that reads the questions (default: the configured one)"),
               effort: str = typer.Option(None, help="low, medium or high"),
               questions: Path = typer.Option(EVAL_DIR / "questions.toml"), only: str = typer.Option(None),
               out: Path = typer.Option(EVAL_DIR / "runs")):
    """Score how each question is read (the filters chosen). Costs a little: one model call per question."""
    from hansard.evaluate import run_plans, save
    from hansard.rag.pipeline import Pipeline

    settings = _settings()
    today, qs = _eval_setup(questions, only)
    parties = Pipeline(settings).parties()
    res = run_plans(settings, qs, today, _client(), parties, model, effort)
    path = save(out, f"plans-{res['model']}", res)
    typer.echo(json.dumps(res["summary"], indent=1))
    typer.echo(f"saved {path}")


@eval_app.command("sources")
def eval_sources(plans: Path = typer.Option(..., help="a saved plans run: the filters each question was read as"),
                 variant: list[str] = typer.Option(["baseline"], help="baseline or rerank:<model>[:question|keywords|both[:weight]]"),
                 judge: str = typer.Option("claude-haiku-5-5", help="model that grades relevance"),
                 questions: Path = typer.Option(EVAL_DIR / "questions.toml"), only: str = typer.Option(None),
                 out: Path = typer.Option(EVAL_DIR / "runs"),
                 judgments: Path = typer.Option(EVAL_DIR / "judgments.jsonl")):
    """Compare ranking variants on the relevance and balance of the sources they choose."""
    from hansard.evaluate import (
        judge_sources,
        judgments_load,
        parse_variant,
        run_sources,
        save,
        summarise_sources,
    )

    settings = _settings()
    today, qs = _eval_setup(questions, only)
    plan_map = _load_plans(plans)
    runs = []
    for v in variant:
        typer.echo(f"{v}:")
        run = run_sources(settings, plan_map, qs, today, parse_variant(v))
        save(out, f"sources-{v.replace(':', '_').replace('/', '-')}", run)
        runs.append(run)
    graded = judge_sources(settings, _client(), qs, runs, judgments, judge)
    known = judgments_load(judgments)
    summaries = [summarise_sources(r, known) for r in runs]
    for sm in summaries:
        typer.echo(json.dumps({k: v for k, v in sm.items() if k != "per_question"}))
    typer.echo(f"grading cost ${graded['cost_usd']} ({graded['graded']} passages graded)")
    save(out, "sources-summary", {"summaries": summaries, "grading": graded})


@eval_app.command("briefings")
def eval_briefings(plans: Path = typer.Option(...), model: list[str] = typer.Option(["claude-opus-5-5"]),
                   judge: str = typer.Option("claude-opus-5-5", help="model for the side-by-side judgement"),
                   questions: Path = typer.Option(EVAL_DIR / "questions.toml"), only: str = typer.Option(None),
                   out: Path = typer.Option(EVAL_DIR / "runs")):
    """Write briefings with each model (about $0.06-0.15 each) and compare them; the first model is the baseline."""
    from hansard.evaluate import compare_briefings, run_briefings, save

    settings = _settings()
    today, qs = _eval_setup(questions, only)
    plan_map, client = _load_plans(plans), _client()
    runs = []
    for m in model:
        typer.echo(f"{m}:")
        run = run_briefings(settings, plan_map, qs, today, client, m)
        save(out, f"briefings-{m}", run)
        typer.echo(json.dumps(run["summary"]))
        runs.append(run)
    for other in runs[1:]:
        cmp = compare_briefings(settings, client, runs[0], other, judge)
        save(out, f"compare-{runs[0]['model']}-{other['model']}", cmp)
        typer.echo(json.dumps({k: cmp[k] for k in ("a", "b", "tally", "cost_usd")}))


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())

__all__ = ["app", "shutil"]
