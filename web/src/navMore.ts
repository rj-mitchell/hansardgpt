/** The header's "More" menu: closes on Escape or a click elsewhere, and is marked when the page is inside it. */
export function setUpNavMore(): void {
  const here = window.location.pathname.replace(/\.html$/, "");
  for (const menu of document.querySelectorAll<HTMLDetailsElement>(".nav-more")) {
    if ([...menu.querySelectorAll("a")].some((a) => a.pathname === here)) menu.classList.add("current");
  }
  document.addEventListener("click", (e) => {
    for (const menu of document.querySelectorAll<HTMLDetailsElement>(".nav-more[open]")) {
      if (!menu.contains(e.target as Node)) menu.open = false;
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    for (const menu of document.querySelectorAll<HTMLDetailsElement>(".nav-more[open]")) {
      menu.open = false;
      menu.querySelector("summary")?.focus();
    }
  });
}
