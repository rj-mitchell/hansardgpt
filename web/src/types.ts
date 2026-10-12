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
  settlement?: string | null;
  urban_area?: string | null;
  urban_area_pop?: number | null;
  party: string | null;
  offices: Office[];
  other_names: string[];
  gender?: "F" | "M" | null;          // as recorded by Parliament
  age?: number | null;                // on the date of the record, not today
  age_approximate?: boolean | null;   // only the year of birth is known
  age_band?: string | null;
  first_elected?: string | null;       // first elected to the Commons
  first_term?: boolean | null;         // still in the Parliament they were first elected to, on the date
  majority_band?: string | null;
  majority_then?: Majority | null;     // from the last election in their seat before the date
  majority_now?: (Majority & { constituency: string }) | null;
}

export interface Majority {
  majority: number;
  pct: number | null;
  band: string | null;
  election: string;
  date: string;
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
  kind: "record" | "division" | "edm" | "devolved" | "evidence";
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
  debate_path?: string | null;
  url_kind?: string | null;
  speaker?: Speaker | null;
  speaker_name_raw?: string | null;
  context?: string | null;
  ranking?: Ranking | null;
  group?: string;
  // divisions
  number?: number;
  ayes?: number;
  noes?: number;
  major_heading?: string | null;
  minor_heading?: string | null;
  party_votes?: Record<string, { aye: number; no: number }>;
  rebels?: Rebel[];
  scope_note?: string;
  vote_type?: VoteType;
  // early day motions
  edm_id?: number;
  edm_title?: string;
  motion_text?: string | null;
  sponsor?: { name: string | null; party: string | null; number?: number | null; slug?: string | null };
  party_counts?: [string, number][];
  sponsors_count?: number | null;
  // devolved parliaments
  legislature?: string;
  member?: { name: string | null; party: string | null; seat: string | null; number?: number | null; slug?: string | null };
  declared?: string | null; // the speaker's own declaration of an interest, as said
  // oral evidence to committees
  committee?: string;
  inquiry?: string | null;
  inquiry_id?: number | null;
  session_id?: number;
  witness?: { name: string; organisation: string | null; role: string | null };
}

/** What a division was on, read from the motion and outcome recorded around it. */
export interface VoteType {
  kind: string;
  label: string;
  note: string;
  question: string;
  outcome: string;
  title?: string;
  aye_means?: string;
  no_means?: string;
  whips?: { party: string; direction: string | null; priority: string | null }[];
  whip_text?: string;
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
  genders?: string[];
  age_bands?: string[];
  tenure?: string[];
  majority_bands?: string[];
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
  group_by?: "role" | "gender" | "age" | "tenure" | "majority";
  /** sides compared, each searched separately */
  compare?: CompareSide[];
}

export interface CompareSide {
  kind: "party" | "person" | "nation";
  id: string;
  label?: string;
}

export interface Segment {
  text: string;
  sources: number[];
  cited: { source: number; cited_text: string }[];
  status: "cited" | "connective" | "unsupported" | "invalid";
  loaded?: { start: number; end: number; word: string }[];
  /** quotations not found word for word in the sources cited for them */
  misquotes?: { start: number; end: number; text: string }[];
}

export interface Answer {
  segments: Segment[];
  markdown: string;
  no_records: boolean;
  citations_total: number;
  citations_invalid: number;
  grounded_ratio: number;
  unsupported_segments: number;
  loaded_words?: number;
  quotes_total?: number;
  quotes_unverified?: number;
}

export interface Scope {
  written: boolean;
  pbc: boolean;
  votes: boolean;
  edms?: boolean;
  devolved?: boolean;
  evidence?: boolean;
}

export interface Settings {
  mode: "summary" | "comprehensive";
  recency: number;
  roleWeight: number;
  scope: Scope;
}

export interface Evidence {
  records: number;
  speakers: number;
  divisions: number;
  date_from: string | null;
  date_to: string | null;
  groups: Record<string, number>;
  parties: Record<string, number>;
  seat_types: Record<string, number>;
  genders?: Record<string, number>;
  age_bands?: Record<string, number>;
  imbalance?: { party: string; count: number; total: number } | null;
  devolution?: { subject: string; name: string; text: string }[];
  edms?: number;
  devolved?: number;
  committee_evidence?: number;
  tenure?: Record<string, number>;
  majority_bands?: Record<string, number>;
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
  evidence?: Evidence;
  streamText: string;
  answer?: Answer | null;
  status: TurnStatus;
  error?: string;
  note?: string;
  briefingKey?: string;
  briefingId?: string;
  preparedAt?: string;
  recordsUpTo?: string | null;
  /** loaded from a shared address (/b/<id>) rather than asked in this visit */
  shared?: boolean;
  /** shown as a topic briefing (/topics/<slug>) */
  topic?: TopicInfo;
}

export interface TopicInfo {
  slug: string;
  title: string;
  area: string;
  question: string;
  description: string;
  refresh_days: number;
  versions?: { briefing_id: string; prepared_at: string; records_up_to: string | null }[];
}

/** /api/topics/<slug>: the topic, its current briefing (if written yet) and every version. */
export interface TopicDetail {
  topic: TopicInfo;
  briefing: SavedBriefing | null;
  versions: { briefing_id: string; prepared_at: string; records_up_to: string | null }[];
}

/** A kept briefing, as returned by /api/briefings/<id>. */
export interface SavedBriefing {
  id: string;
  question: string;
  created_at: string;
  records_up_to: string | null;
  plan: Plan | null;
  sources: SourceCard[];
  candidates?: number;
  semantic?: boolean;
  evidence?: Evidence;
  answer: Answer | null;
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
  donate_url?: string | null;
}

export interface Highlight {
  source: number;
  quotes: string[];
}
