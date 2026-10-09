export interface Office {
  kind: string;
  title: string;
  role?: string;
  portfolios?: string[];
  committee_name?: string | null;
}

export interface Speaker {
  person_id: string | null;
  date: string;
  name: string | null;
  house: string | null;
  constituency: string | null;
  region: string | null;
  nation?: string | null;
  party: string | null;
  offices: Office[];
  other_names: string[];
}

export interface Ranking {
  score: number;
  relevance: number;
  keyword: number | null;
  semantic: number | null;
  recency: number;
  authority: number;
  authority_reason: string;
}

export interface Rebel {
  name: string | null;
  party: string | null;
  constituency: string | null;
  region: string | null;
  vote: string;
  majority: string;
}

export interface SourceCard {
  n: number;
  kind: "record" | "division";
  title: string;
  url: string;
  date: string;
  chamber: string;
  text: string;
  twfy_url: string;
  record_id?: string;
  record_type?: string;
  heading?: string;
  colnum?: string | null;
  uin?: string | null;
  time?: string | null;
  official_url?: string | null;
  url_kind?: string | null;
  speaker?: Speaker | null;
  speaker_name_raw?: string | null;
  context?: string | null;
  ranking?: Ranking | null;
  // divisions
  number?: number;
  ayes?: number;
  noes?: number;
  major_heading?: string | null;
  minor_heading?: string | null;
  party_votes?: Record<string, { aye: number; no: number }>;
  rebels?: Rebel[];
  scope_note?: string;
}

export interface Filters {
  date_from: string | null;
  date_to: string | null;
  houses: string[];
  regions: string[];
  parties: string[];
  person_ids: string[];
  offices: string[];
  record_types: string[];
}

export interface Plan {
  question: string;
  search_text: string;
  filters: Filters;
  portfolios: string[];
  wants_votes: boolean;
  speakers: { person_id: string; name: string; query?: string }[];
  unresolved_speakers: string[];
  interpretation: string;
  parser: string;
}

export interface Segment {
  text: string;
  sources: number[];
  cited: { source: number; cited_text: string }[];
  status: "cited" | "connective" | "unsupported" | "invalid";
}

export interface Answer {
  segments: Segment[];
  markdown: string;
  no_records: boolean;
  citations_total: number;
  citations_invalid: number;
  grounded_ratio: number;
  unsupported_segments: number;
}

export interface Scope {
  written: boolean;
  pbc: boolean;
  votes: boolean;
}

export interface Settings {
  mode: "summary" | "comprehensive";
  recency: number;
  roleWeight: number;
  scope: Scope;
}

export type TurnStatus = "planning" | "searching" | "answering" | "verifying" | "done" | "error";

export interface Turn {
  id: string;
  question: string;
  settings: Settings;
  plan?: Plan;
  sources: SourceCard[];
  candidates?: number;
  semantic?: boolean;
  streamText: string;
  answer?: Answer | null;
  status: TurnStatus;
  error?: string;
  note?: string;
}

export interface Meta {
  regions: string[];
  region_groups: Record<string, string[]>;
  portfolios: Record<string, string>;
  parties: { id: string; name: string }[];
  answers_enabled: boolean;
  model: string;
  archive_start: string;
  index: { passages: number; vectors: number };
  last_sync: { finished_at: string | null; status: string } | null;
  defaults: { recency: number; role_weight: number };
  attribution: { text: string; url: string }[];
}

export interface Highlight {
  source: number;
  quotes: string[];
}
