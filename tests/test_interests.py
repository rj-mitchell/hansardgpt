from datetime import date
from types import SimpleNamespace

from hansard.rag.interests import Match, Matches, check, held_on
from hansard.rag.sources import Source

GIFT = {"type": "3", "name": "Gifts, benefits and hospitality from UK sources", "items": [
    {"summary": "Betting & Gaming Council - £1,920.00", "details": [["Payment Description", "Tickets at Ascot"]],
     "registered": "02 July 2026", "children": []},
    {"summary": "Old gift - £500.00", "details": [], "registered": "01 March 2025", "children": []}]}
LAND = {"type": "6", "name": "Land and property (within or outside the UK)", "items": [
    {"summary": "Agricultural in County Fermanagh", "details": [], "registered": "10 January 2020", "children": []},
    {"summary": "Flat in London", "details": [], "registered": "10 October 2026", "children": []}]}
LORDS = {"type": "1", "name": "Remunerated employment etc.", "items": [
    {"summary": "Non-executive Director, Ofcom", "details": [], "registered_on": "2025-05-07", "children": []},
    {"summary": "Chair, a bank (interest ceased 30 April 2026)", "details": [], "registered_on": "2022-07-04",
     "children": []}]}


def test_entries_that_applied_on_the_day():
    held = held_on([GIFT, LAND], date(2026, 9, 10), lords=False)
    assert [h["summary"] for h in held] == ["Betting & Gaming Council - £1,920.00", "Agricultural in County Fermanagh"]
    # a gift more than a year before is left out; ongoing interests stay; anything registered later is left out
    assert "Ascot" in held[0]["text"]
    assert [h["summary"] for h in held_on([LORDS], date(2025, 5, 6), lords=True)] == [
        "Chair, a bank (interest ceased 30 April 2026)"]  # the Ofcom role was registered the next day
    assert [h["summary"] for h in held_on([LORDS], date(2025, 6, 1), lords=True)] == [
        "Non-executive Director, Ofcom", "Chair, a bank (interest ceased 30 April 2026)"]
    # an interest that had ended before the day does not count
    assert [h["summary"] for h in held_on([LORDS], date(2026, 6, 1), lords=True)] == ["Non-executive Director, Ofcom"]
    ended = {"type": "1.2", "name": "Ongoing paid employment", "items": [
        {"summary": "Adviser", "details": [["End Date", "2026-01-31"]], "registered": "01 May 2025", "children": []}]}
    assert held_on([ended], date(2026, 3, 1), lords=False) == []
    assert len(held_on([ended], date(2025, 12, 1), lords=False)) == 1


class Register:
    def __init__(self, people):
        self.people = people

    def for_person(self, pid):
        return {"categories": self.people.get(pid, [])}


class Lords:
    def for_person(self, pid):
        return [{"register": "lords", "categories": [LORDS]}] if pid == "uk.org.publicwhip/person/3" else []


class Client:
    def __init__(self, matches):
        self.matches = matches
        self.prompt = ""
        self.messages = self

    def parse(self, **kw):
        self.prompt = kw["messages"][0]["content"]
        return SimpleNamespace(parsed_output=Matches(matches=self.matches), usage=SimpleNamespace(input_tokens=1))


def source(n, pid, house, text, day="2026-09-10"):
    return Source(n, "record", "t", "u", [text], {"speaker": {"person_id": f"uk.org.publicwhip/person/{pid}",
                                                              "name": f"Member {pid}", "house": house},
                                                  "date": day, "heading": "Debate", "text": text})


def test_check_keeps_only_real_matches():
    commons = Register({"uk.org.publicwhip/person/1": [GIFT], "uk.org.publicwhip/person/2": [LAND]})
    sources = [source(1, 1, "commons", "Gambling advertising"), source(2, 2, "commons", "Farm tax"),
               source(3, 3, "lords", "Ofcom codes"), source(4, 9, "commons", "No register entries")]
    client = Client([Match(contribution=1, interest="A1", connection="Gift from the gambling industry; gambling."),
                     Match(contribution=2, interest="A1", connection="Another member's entry."),
                     Match(contribution=2, interest="Q7", connection="A label that does not exist."),
                     Match(contribution=3, interest="C1", connection="Ofcom role; Ofcom codes.")])
    flags, usage = check(client, "m", "question", sources, commons, Lords())
    assert usage is not None and "Member 9" not in client.prompt
    assert [(f["source"], f["name"], [i["summary"] for i in f["items"]]) for f in flags] == [
        (1, "Member 1", ["Betting & Gaming Council - £1,920.00"]),
        (3, "Member 3", ["Non-executive Director, Ofcom"])]
    assert flags[0]["link"] == "/people/1#h-interests" and flags[1]["register"] == "Register of Lords' Interests"


def test_no_model_call_without_entries():
    client = Client([])
    assert check(client, "m", "q", [source(1, 9, "commons", "x")], Register({}), Lords()) == ([], None)
    assert client.prompt == ""
