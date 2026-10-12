/** The site's links, in one place. The header holds what people use, the distinctive features first, then the
 * ways to browse the record behind "More"; the footer holds pages about the site. partials/header.html and
 * partials/footer.html carry the same lists for the static pages; a test keeps them in step. */
export interface NavLink {
  href: string;
  label: string;
}

export const NAV: NavLink[] = [
  { href: "/", label: "Ask a question" },
  { href: "/people", label: "MPs and peers" },
  { href: "/topics", label: "Topics" },
  { href: "/compare", label: "Compare" },
  { href: "/this-week", label: "This week" },
  { href: "/bills", label: "Bills" },
];

export const MORE: NavLink[] = [
  { href: "/timeline", label: "Timelines" },
  { href: "/charts", label: "Charts" },
  { href: "/edms", label: "Early day motions" },
  { href: "/committees", label: "Committees" },
  { href: "/witnesses", label: "Committee witnesses" },
  { href: "/devolved", label: "Devolved parliaments" },
  { href: "/donations", label: "Donations" },
  { href: "/directorships", label: "Company roles" },
  { href: "/groups", label: "All-party groups" },
];

export const FOOTER: NavLink[] = [
  { href: "/about", label: "About" },
  { href: "/methodology", label: "Methodology" },
  { href: "/glossary", label: "Glossary" },
  { href: "/resources", label: "Other resources" },
  { href: "/developers", label: "Data and API" },
  { href: "/press", label: "Press and contact" },
  { href: "/changelog", label: "Changelog" },
  { href: "/status", label: "Status" },
  { href: "/corrections", label: "Corrections" },
  { href: "/corrections#report", label: "Report a problem" },
  { href: "/accessibility", label: "Accessibility" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "https://github.com/rj-mitchell/hansardgpt", label: "Source code" },
];
