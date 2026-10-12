import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV } from "../nav";

describe("site navigation", () => {
  it("is the same on the home page and the static pages, with Ask a question first", () => {
    const html = readFileSync(resolve(__dirname, "../../partials/header.html"), "utf8");
    const links = [...html.matchAll(/<a href="([^"]+)">([^<]+)<\/a>/g)].map((m) => ({ href: m[1], label: m[2] }));
    const nav = links.filter((l) => NAV.some((n) => n.href === l.href));
    expect(nav).toEqual(NAV);
    expect(NAV[0]).toEqual({ href: "/", label: "Ask a question" });
  });
});
