import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { FOOTER, MORE, NAV } from "../nav";

/** The links inside a partial's <nav> element. */
const links = (file: string) => {
  const html = readFileSync(resolve(__dirname, "../../partials", file), "utf8");
  const nav = html.slice(html.indexOf("<nav"), html.indexOf("</nav>"));
  return [...nav.matchAll(/<a href="([^"]+)">([^<]+)<\/a>/g)].map((m) => ({ href: m[1], label: m[2] }));
};

describe("site navigation", () => {
  it("the static pages' header matches the home page's, with Ask a question first", () => {
    expect(links("header.html")).toEqual([...NAV, ...MORE]);
    expect(NAV[0]).toEqual({ href: "/", label: "Ask a question" });
  });

  it("the footer is the same everywhere and holds only pages about the site", () => {
    expect(links("footer.html")).toEqual(FOOTER);
    const header = new Set([...NAV, ...MORE].map((l) => l.href));
    expect(FOOTER.filter((l) => header.has(l.href))).toEqual([]);
  });
});
