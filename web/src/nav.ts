/** The site's main navigation, in order: the distinctive features first (asking, then people and ready-made
 * briefings), then ways to browse the record. partials/header.html carries the same list for the static pages;
 * a test keeps the two in step. */
export const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Ask a question" },
  { href: "/people", label: "MPs and peers" },
  { href: "/topics", label: "Topics" },
  { href: "/compare", label: "Compare" },
  { href: "/this-week", label: "This week" },
  { href: "/bills", label: "Bills" },
  { href: "/timeline", label: "Timelines" },
  { href: "/charts", label: "Charts" },
  { href: "/about", label: "About" },
];
