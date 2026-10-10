/** Script for the static pages (methodology, changelog, status): styles, a cookie-free page count, live status. */
import "@fontsource-variable/source-serif-4/opsz.css";
import "@fontsource-variable/source-serif-4/opsz-italic.css";
import "./styles.css";
import { api } from "./api";
import { fmtDate } from "./render";

void api.hit(window.location.pathname, document.referrer);

for (const a of document.querySelectorAll<HTMLAnchorElement>(".page-nav a")) {
  if (a.pathname === window.location.pathname.replace(/\.html$/, "")) a.setAttribute("aria-current", "page");
}

interface Status {
  archive_start: string;
  latest_record: string | null;
  last_update: { finished_at: string | null; status: string } | null;
  briefings: "available" | "paused" | "unavailable";
  briefings_note: string | null;
  passages: number;
  meaning_search_coverage: number;
}

const BRIEFINGS: Record<Status["briefings"], string> = {
  available: "Available",
  paused: "Paused",
  unavailable: "Unavailable (sources only)",
};

function row(dl: HTMLElement, term: string, value: string, state?: string) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  if (state) dd.dataset.state = state;
  dl.append(dt, dd);
}

async function showStatus(el: HTMLElement) {
  try {
    const resp = await fetch("/api/status");
    if (!resp.ok) throw new Error(String(resp.status));
    const s = (await resp.json()) as Status;
    const dl = document.createElement("dl");
    dl.className = "status-list";
    row(dl, "Briefings", BRIEFINGS[s.briefings] + (s.briefings_note ? `. ${s.briefings_note}` : ""), s.briefings);
    row(dl, "Search", "Available", "available");
    row(dl, "Most recent record", s.latest_record ? fmtDate(s.latest_record) : "Not yet loaded");
    if (s.last_update?.finished_at) {
      const at = new Date(s.last_update.finished_at);
      row(
        dl,
        "Last update",
        `${fmtDate(s.last_update.finished_at.slice(0, 10))} at ${at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })} (${s.last_update.status === "ok" ? "completed" : s.last_update.status})`,
        s.last_update.status === "ok" ? "available" : "paused",
      );
    }
    row(dl, "Archive", `From ${fmtDate(s.archive_start)}: ${s.passages.toLocaleString("en-GB")} passages`);
    row(
      dl,
      "Meaning-based search",
      `Covers ${Math.round(s.meaning_search_coverage * 100)}% of passages so far (newest first); keyword search covers all of them`,
    );
    el.replaceChildren(dl);
  } catch {
    el.textContent = "The status service could not be reached. If this page loads but briefings do not, the site may be restarting.";
  }
}

const live = document.getElementById("status-live");
if (live) void showStatus(live);
