// Mirrors of the backend's Pydantic schemas (only the fields the UI reads).

export type Role = "ADMIN" | "SECURITY_ANALYST" | "AGENT";

export interface User {
  username: string;
  role: Role;
}

export type FirewallAction = "ALLOW" | "FLAG" | "BLOCK";
export type Channel = "USER_INPUT" | "RETRIEVED" | "TOOL_OUTPUT" | "TOOL_ARGUMENTS";
export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TrustLevel = "UNTRUSTED" | "LOW" | "MEDIUM" | "HIGH" | "VERIFIED";
export type SubjectType = "AGENT" | "SOURCE" | "TOOL";

export interface RuleMatch {
  rule_id: string;
  category: string;
  weight: number;
  excerpt: string;
}

export interface FirewallVerdict {
  action: FirewallAction;
  score: number;
  channel: Channel;
  matches: RuleMatch[];
  categories: string[];
  reason: string;
}

export interface RuleInfo {
  rule_id: string;
  category: string;
  weight: number;
  description: string;
}

export interface SecurityEvent {
  id: string;
  event_type: string;
  severity: Severity;
  agent: string | null;
  session_id: string | null;
  source: string;
  description: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface TelemetrySummary {
  total_events: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  by_agent: Record<string, number>;
  decisions: { component: string; allowed: number; denied: number }[];
}

export interface TrustScore {
  subject_type: SubjectType;
  subject_id: string;
  score: number;
  level: TrustLevel;
  updated_at: string;
  assessments: number;
}

export interface TrustAssessment {
  subject_type: SubjectType;
  subject_id: string;
  score: number;
  previous: number;
  level: TrustLevel;
  signal: string;
  rationale: string | null;
  assessed_by: string;
  created_at: string;
}

export interface TrustDetail extends TrustScore {
  history: TrustAssessment[];
}

export interface AgentInfo {
  name: string;
  trust_score: number;
  trust_level: TrustLevel;
  allowed_tools: string[];
  blocked_tools: string[];
  allowed_domains: string[];
  sensitive_data: string[];
}

export interface CheckResult {
  checkpoint: string;
  passed: boolean;
  detail: string;
}

export interface ToolCall {
  id: string;
  agent: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: "PENDING" | "APPROVED" | "DENIED" | "EXECUTED" | "FAILED";
  decision_reason: string;
  checks: CheckResult[];
  output: string | null;
  output_action: FirewallAction | null;
  redactions: Record<string, number>;
  requested_at: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  enabled: boolean;
  required_trust: number;
  rate_limit_per_min: number | null;
  data_category: string | null;
  parameters: Record<string, string>;
  domain_checked_argument: string | null;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_title: string;
  source: string;
  source_trust: number;
  similarity: number;
  content: string;
  sanitized: boolean;
}

export interface DroppedChunk {
  chunk_id: string;
  document_title: string;
  source: string;
  reason: string;
}

export interface RetrievalResult {
  query: string;
  chunks: RetrievedChunk[];
  dropped: DroppedChunk[];
}

export interface SourceSummary {
  source: string;
  trust_level: TrustLevel;
  trust_score: number;
  documents: number;
  chunks_indexed: number;
}

export interface KbStats {
  index_ready: boolean;
  embedder: string;
  documents: number;
  bytes_ingested: number;
  chunks_screened: number;
  chunks_indexed: number;
  chunks_flagged: number;
  chunks_quarantined: number;
  sources: string[];
  source_summaries: SourceSummary[];
  memory_bytes: number;
  persisted: boolean;
}

export type IngestStage =
  "QUEUED" | "PARSING" | "SCREENING" | "EMBEDDING" | "INDEXING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface IngestJob {
  id: string;
  filename: string;
  title: string;
  source: string;
  trust_level: TrustLevel;
  origin: "upload" | "inbox";
  size_bytes: number;
  bytes_read: number;
  stage: IngestStage;
  chunks_total: number;
  chunks_indexed: number;
  chunks_flagged: number;
  chunks_quarantined: number;
  document_id: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface InboxListing {
  directory: string;
  files: { path: string; size_bytes: number; supported: boolean }[];
  supported_extensions: string[];
}

export interface DocumentChunkView {
  chunk_index: number;
  content: string;
  firewall_action: FirewallAction;
  firewall_score: number;
}

export interface QuarantinedChunk {
  chunk_id: string;
  document_title: string;
  source: string;
  score: number;
  categories: string[];
  excerpt: string;
}

export interface IngestReport {
  document_id: string;
  title: string;
  source: string;
  chunks_total: number;
  chunks_indexed: number;
  chunks_flagged: number;
  chunks_quarantined: number;
  trust_level: TrustLevel;
  source_type: string;
  filename: string | null;
  size_bytes: number;
  created_at: string;
}

export interface TraceEntry {
  stage: string;
  status: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface AgentTurn {
  id: string;
  session_id: string;
  agent: string;
  message: string;
  answer: string;
  blocked: boolean;
  brain: string;
  trace: TraceEntry[];
  tool_calls: ToolCall[];
  context: RetrievedChunk[];
  dropped: DroppedChunk[];
  redactions: Record<string, number>;
  duration_ms: number;
  created_at: string;
}

export interface RunProgress {
  request_id: string;
  status: "running" | "completed" | "blocked" | "failed";
  current_stage: string | null;
  stages: TraceEntry[];
  started_at: string;
  finished_at: string | null;
}

export interface SessionSummary {
  id: string;
  agent: string;
  owner: string;
  status: "ACTIVE" | "CLOSED" | "TERMINATED";
  created_at: string;
  turns: number;
  blocked_turns: number;
}

export interface SessionRecord {
  id: string;
  agent: string;
  owner: string;
  status: "ACTIVE" | "CLOSED" | "TERMINATED";
  created_at: string;
  turns: AgentTurn[];
}

export interface AgentPolicy {
  agent: string;
  allowed_tools: string[];
  blocked_tools: string[];
  allowed_domains: string[];
  sensitive_data: string[];
}
