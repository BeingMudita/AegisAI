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
  decided_at?: string | null;
  session_id?: string | null;
  expires_at?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
  reviewed_at?: string | null;
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
  requires_approval?: boolean;
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
  /** Set when the same content was already indexed (the existing document's id). */
  duplicate_of: string | null;
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

export type SessionStatus = "ACTIVE" | "CLOSED" | "TERMINATED" | "EXPIRED";

/** Tokens (and cost) one turn consumed; estimated when no LLM reported counts. */
export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  llm_calls: number;
  estimated: boolean;
  cost_usd: number;
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
  usage?: TokenUsage | null;
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
  status: SessionStatus;
  created_at: string;
  turns: number;
  blocked_turns: number;
}

export interface SessionRecord {
  id: string;
  agent: string;
  owner: string;
  status: SessionStatus;
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

// ---------------------------------------------------------------- approvals
export interface ApprovalQueue {
  pending: ToolCall[];
  recent: ToolCall[];
  ttl_minutes: number;
}

// ----------------------------------------------------------------- red team
export type Suite = "firewall" | "agents";

export interface CaseResult {
  id: string;
  category: string;
  channel: Channel;
  malicious: boolean;
  action: FirewallAction;
  score: number;
  rules: string[];
  detected: boolean;
  correct: boolean;
  latency_ms: number;
  text: string;
}

export interface CategoryStat {
  category: string;
  n: number;
  detected: number;
  blocked: number;
  detection_rate: number;
}

export interface FirewallReport {
  cases: number;
  malicious: number;
  benign: number;
  confusion: { tp: number; fp: number; tn: number; fn: number };
  precision: number;
  recall: number;
  f1: number;
  false_positive_rate: number;
  block_rate_malicious: number;
  block_rate_benign: number;
  latency_ms: { p50: number; p95: number; max: number };
  by_category: CategoryStat[];
  results: CaseResult[];
  misses: CaseResult[];
  false_positives: CaseResult[];
}

export interface ScenarioResult {
  id: string;
  title: string;
  agent: string;
  message: string;
  passed: boolean;
  failures: string[];
  blocked: boolean;
  tools: string[];
  duration_ms: number;
}

export interface AgentReport {
  scenarios: number;
  passed: number;
  pass_rate: number;
  results: ScenarioResult[];
}

export interface RedTeamRun {
  id: string;
  status: "running" | "completed" | "failed";
  suites: Suite[];
  started_by: string;
  started_at: string;
  finished_at: string | null;
  progress_done: number;
  progress_total: number;
  firewall: FirewallReport | null;
  /** The same benchmark on cases the rules were never tuned on (runs with "firewall"). */
  holdout: FirewallReport | null;
  agents: AgentReport | null;
  error: string | null;
}

export interface RunSummary {
  id: string;
  status: RedTeamRun["status"];
  suites: Suite[];
  started_by: string;
  started_at: string;
  finished_at: string | null;
  recall: number | null;
  precision: number | null;
  false_positive_rate: number | null;
  holdout_recall: number | null;
  holdout_false_positive_rate: number | null;
  scenarios_passed: number | null;
  scenarios_total: number | null;
}

export interface SuiteInfo {
  firewall: { cases: number; malicious: number; categories: Record<string, number>; holdout_cases: number };
  agents: { scenarios: number; items: { id: string; title: string; agent: string }[] };
}

// --------------------------------------------------------------- scanner
export type RiskSeverity = "LOW" | "MEDIUM" | "HIGH";

export interface ScanToolProfile {
  name: string;
  risk_level: string;
  data_category: string | null;
  external: boolean;
  domain_kind: string | null;
  requires_approval: boolean;
  min_trust: number;
  allowed: boolean;
  enabled: boolean;
  source: string;
}

export interface ScanDataSource {
  name: string;
  kind: string;
  trust: number | null;
  untrusted: boolean;
}

export interface ScanDataFlow {
  label: string;
  sensitive: boolean;
  external: boolean;
  risk: RiskSeverity;
}

export interface AgentProfile {
  name: string;
  llm: string;
  aegis_integrated: boolean;
  source: string;
  tools: ScanToolProfile[];
  data_sources: ScanDataSource[];
  external_destinations: string[];
  allowed_tools: string[];
  allowed_domains: string[];
  sensitive_data: string[];
  trust_minimum: number;
  data_flows: ScanDataFlow[];
  notes: string[];
}

export interface RiskFinding {
  category: string;
  severity: RiskSeverity;
  title: string;
  detail: string;
  fix: string | null;
  owasp: string | null;
}

export interface SecurityReport {
  agent: string;
  score: number;
  grade: string;
  findings: RiskFinding[];
  generated_policy: string;
  owasp: { id: string; name: string; status: string }[];
  attack_results: Record<string, unknown> | null;
  profile: AgentProfile;
}

export interface ScannerPolicy {
  agent: string;
  aegis_yaml: string;
}

export interface ScannerTestResult {
  agent: string;
  passed: number;
  total: number;
  scenarios: ScenarioResult[];
}

// ------------------------------------------------------------ threat coverage
export type CoverageStatus = "mitigated" | "partial" | "gap";

export interface Control {
  id: string;
  name: string;
  description: string;
  page: string | null;
  code: string[];
}

export interface Evidence {
  kind: "category" | "scenario" | "test";
  ref: string;
  label: string;
  status: "pass" | "weak" | "fail" | "not_run" | "static";
  detail: string | null;
}

export interface ThreatCoverage {
  id: string;
  name: string;
  description: string;
  status: CoverageStatus;
  controls: string[];
  evidence: Evidence[];
  residual: string;
  verified: boolean | null;
}

export interface Framework {
  id: string;
  name: string;
  version: string;
  url: string;
  items: ThreatCoverage[];
  summary: Partial<Record<CoverageStatus, number>>;
}

export interface CoverageReport {
  generated_at: string;
  frameworks: Framework[];
  controls: Control[];
  evidence_run: RunSummary | null;
}
