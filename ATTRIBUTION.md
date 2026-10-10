# Data sources and attribution

Hansard Guru is built entirely on open data. The application shows these
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
