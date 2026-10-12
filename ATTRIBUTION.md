# Data sources and attribution

Where They Stand is built entirely on open data. The application shows these
attributions in its footer and on its About page.

## Parliamentary proceedings (Hansard)

Contains Parliamentary information licensed under the
[Open Parliament Licence v3.0](https://www.parliament.uk/site-information/copyright-parliament/open-parliament-licence/).

Debates, written answers, written ministerial statements, Public Bill Committee
debates and division records are taken from the structured XML published by
[TheyWorkForYou](https://www.theyworkforyou.com/) / [ParlParse](https://parser.theyworkforyou.com/),
a project of [mySociety](https://www.mysociety.org/). Every excerpt the
application displays keeps a link back to its primary Hansard record.

## Members, offices and committees

People, names, seats, parties, ministerial and shadow posts, and select
committee memberships come from the `members/` data in
[mysociety/parlparse](https://github.com/mysociety/parlparse), which draws on
the UK Parliament Members' Names Information Service (Open Parliament Licence
v3.0). With thanks to mySociety for maintaining these datasets.

## Early day motions, committees, interests and the devolved parliaments

Early day motions and their signatures come from the UK Parliament
[oral questions and motions API](https://oralquestionsandmotions-api.parliament.uk/), and committees, inquiries,
reports, government responses and oral evidence witnesses from the UK Parliament
[Committees API](https://committees-api.parliament.uk/), both under the Open Parliament Licence v3.0.

The Register of Members' Financial Interests, the official reports of the Scottish Parliament, the Senedd and
the Northern Ireland Assembly, and plain-English descriptions of some divisions
([TheyWorkForYou Votes](https://votes.theyworkforyou.com/)) come from the data published by
[TheyWorkForYou](https://www.theyworkforyou.com/pwdata/) (mySociety). The devolved reports contain information
licensed under the Open Parliament Licence and the equivalent licences of the Scottish Parliament, the Senedd and
the Northern Ireland Assembly.

## Registers of interests

The Register of Members' Financial Interests and the registers of the Scottish Parliament, the Senedd and the
Northern Ireland Assembly come from the copies published by [TheyWorkForYou](https://www.theyworkforyou.com/pwdata/)
(mySociety); the Register of Lords' Interests from the UK Parliament
[Members API](https://members-api.parliament.uk/), under the Open Parliament Licence v3.0 and the equivalent
licences of the devolved parliaments.

## Political donations

Donations to MPs and to their local parties come from the
[Electoral Commission's register of donations](https://search.electoralcommission.org.uk/), refreshed weekly,
with donors' addresses and postcodes left out. Matching donations to MPs is this site's own work (see the
methodology page); each entry links to the Commission's record of it.

## All-party and cross-party groups

Groups, officers, members, secretariats and registered benefits come from mySociety's
[APPG groups and memberships](https://github.com/mysociety/appg-membership) dataset, licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/), which is built from the Register of
All-Party Parliamentary Groups (Open Parliament Licence v3.0) and the devolved parliaments' lists of cross-party
groups. Membership lists found by AI web search are left out; contact details are left out.

## Gender and date of birth

Members' gender and constituency election results (majorities, votes cast, by-elections) come from the UK
Parliament [Members API](https://members-api.parliament.uk/) (Open Parliament Licence v3.0). Dates of birth come
from [Wikidata](https://www.wikidata.org/) (property P569, matched by UK Parliament ID, P10428), whose
structured data is available under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

## Constituency boundaries and regions

Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Source: Office for National Statistics (Westminster Parliamentary Constituencies,
December 2021 names and codes), and mySociety's
[2025-constituencies](https://github.com/mysociety/2025-constituencies) dataset
(post-2024 constituencies with regions, and 2010→2024 boundary overlaps),
itself derived from ONS and Boundary Commission data.
Seat types use ONS 2011 Built-up Areas, 2011 Census populations (Nomis) and ONS output-area lookups
(England and Wales); National Records of Scotland Census 2022 settlements, populations and lookups
(Scotland); and NISRA 2015 settlements, Census 2021 populations and lookups (Northern Ireland). All are
published under the Open Government Licence v3.0.
Contains OS data © Crown copyright and database right.
Contains National Statistics data © Crown copyright and database right.
Contains NRS data © Crown copyright and database right.
Contains NISRA data © Crown copyright.

## Typeface

The web app bundles [Source Serif 4](https://github.com/adobe-fonts/source-serif) (Adobe),
licensed under the [SIL Open Font License 1.1](https://openfontlicense.org), via Fontsource.
No fonts are loaded from third-party servers.

## Typefaces

Preview cards are drawn with Source Serif 4 and Source Sans 3 by Adobe, licensed under the SIL Open Font
License 1.1 (`data_static/fonts/LICENSE-*.md`). The web app uses Source Serif 4 via Fontsource under the same
licence.

## Briefings written by the site

The text of briefings written by Where They Stand is licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
Credit "Where They Stand" with a link to the briefing. Quotations from Hansard within a briefing remain under the
Open Parliament Licence v3.0. The name and mark are not covered by the licence.
