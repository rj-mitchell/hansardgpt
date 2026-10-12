/** The MPs and peers page: find your MP by postcode, or anyone by name, constituency or party. */
import "./pages";

interface Member {
  number: number;
  name: string;
  slug: string;
  house: string;
  constituency: string | null;
  party: string | null;
}

const href = (m: { number: number; slug: string }) => `/people/${m.number}/${m.slug}`;

const form = document.getElementById("postcode-form") as HTMLFormElement;
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("postcode-error")!;
  err.hidden = true;
  const pc = (document.getElementById("postcode") as HTMLInputElement).value.trim();
  if (!pc) return;
  try {
    const r = await fetch(`/api/postcode/${encodeURIComponent(pc)}`);
    const body = await r.json();
    if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "That postcode could not be found.");
    if (!body.number) throw new Error(`${body.constituency} has no MP in the record at present.`);
    window.location.href = href(body);
  } catch (ex) {
    err.textContent = ex instanceof Error ? ex.message : "That postcode could not be found.";
    err.hidden = false;
  }
});

/** One House's members: folded away until opened, except when showing search results. */
function list(title: string, members: Member[], open: boolean): HTMLElement {
  const section = document.createElement("details");
  section.className = "people-group";
  section.open = open;
  const summary = document.createElement("summary");
  const h = document.createElement("h3");
  h.textContent = `${title} (${members.length})`;
  summary.append(h);
  const ul = document.createElement("ul");
  ul.className = "people-list";
  for (const m of members) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = href(m);
    a.textContent = m.name;
    const meta = document.createElement("span");
    meta.className = "muted small";
    meta.textContent = ` ${[m.constituency, m.party].filter(Boolean).join(", ")}`;
    li.append(a, meta);
    ul.append(li);
  }
  section.append(summary, ul);
  return section;
}

async function load() {
  const live = document.getElementById("people-live")!;
  const input = document.getElementById("people-search") as HTMLInputElement;
  try {
    const { people } = (await (await fetch("/api/people")).json()) as { people: Member[] };
    const render = () => {
      const q = input.value.trim().toLowerCase();
      const hit = people.filter((m) => !q || [m.name, m.constituency, m.party].some((x) => x?.toLowerCase().includes(q)));
      const mps = hit.filter((m) => m.house === "commons");
      const peers = hit.filter((m) => m.house === "lords");
      live.replaceChildren(
        ...(hit.length ? [] : [Object.assign(document.createElement("p"), { textContent: "No current member matches." })]),
        ...(mps.length ? [list("MPs", mps, !!q)] : []),
        ...(peers.length ? [list("Members of the House of Lords", peers, !!q)] : []),
      );
    };
    input.addEventListener("input", render);
    render();
  } catch {
    live.textContent = "The list of members could not be loaded. Please try again later.";
  }
}
void load();
