// ---- Enums / string literals ----

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

export type FindingState =
  | 'ADVISORY'
  | 'QUEUED_FOR_VERIFICATION'
  | 'VERIFIED'
  | 'UNVERIFIED'
  | 'EXCEPTION'
  | 'DISMISSED'

export type ScanState =
  | 'INGEST'
  | 'DISCOVER'
  | 'STATIC'
  | 'SEMANTIC'
  | 'NORMALIZE'
  | 'SCORE'
  | 'SELECT_SCENARIOS'
  | 'VERIFY'
  | 'DECIDE'
  | 'HUMAN_GATE'
  | 'REMEDIATE'
  | 'DONE'
  | 'FAILED'

export type DefectClass = 'DUPLICATE_PAYMENT' | 'WEBHOOK_INTEGRITY' | 'AMOUNT_CURRENCY' | 'SUSPICIOUS_CONTENT'

export type DetectorSource = 'STATIC' | 'LLM' | 'BOTH'

export type ExposureKind = 'MEASURED' | 'ESTIMATED'

export type VerificationStatus = 'VERIFIED' | 'NOT_REPRODUCED' | 'INCONCLUSIVE' | 'BLOCKED' | 'ERROR'

export type RemediationStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

// ---- Scan types ----

export interface ScanListItem {
  id: string
  state: ScanState
  repo_locator: string
  started_at: string
  finished_at: string | null
  n_findings: number
  llm_status: 'OK' | 'DEGRADED' | 'FAILED' | null
  static_status: 'OK' | 'DEGRADED' | 'FAILED' | null
}

export interface ScanStats {
  n_critical?: number
  n_high?: number
  n_medium?: number
  n_low?: number
  n_advisory?: number
  n_verified?: number
  n_dismissed?: number
  [key: string]: number | undefined
}

export interface Scan extends ScanListItem {
  stats_json: ScanStats | null
}

export interface ScanSSEEvent {
  state: ScanState
  message: string
}

export interface PreflightResult {
  manifest_present: boolean
  file_count: number
}

// ---- Finding types ----

export interface CodeContext {
  lines: string[]
  highlight_start: number
  highlight_end: number
  file: string
}

export interface VerificationResult {
  id: string
  status: VerificationStatus
  scenario_id?: string
  tier?: string
  observed_behavior?: string | null
  proof_summary?: string | null
  measured_impact_paise?: number | null
  attempts?: number | null
  error_code?: string | null
  started_at?: string | null
  finished_at?: string | null
  // legacy fields kept optional for older payloads
  created_at?: string
  message?: string | null
}

export interface Remediation {
  id: string
  diff: string
  rationale: string
  status: RemediationStatus
  created_at: string
}

export interface FindingListItem {
  id: string
  scan_id: string
  severity: Severity
  state: FindingState
  defect_class: DefectClass
  detector_source: DetectorSource
  title: string
  file_path: string | null
  line_number: number | null
  exposure_kind: ExposureKind | null
  exposure_paise: number | null
  created_at: string
}

export interface GroundingRef {
  id: string
  kind: string
  tier: string
  sample_id?: string | null
  hard_negative?: boolean
}

export interface Grounding {
  analyzer: string
  cited_rule: { id: string; title?: string | null; text: string } | null
  references: GroundingRef[]
}

export interface Finding extends FindingListItem {
  llm_reasoning: string | null
  static_confidence: number | null
  rule_ids: string[]
  assumptions: string | null
  code_context: CodeContext | null
  verification_results: VerificationResult[]
  remediations: Remediation[]
  grounding?: Grounding | null
}

export interface EvalSystemSummary {
  system: string
  n_samples: number
  provider_model: string | null
  macro: { p?: number; r?: number; f1?: number }
  total_fp: number
  per_class: Record<string, { tp?: number; fp?: number; fn?: number; p?: number; r?: number; f1?: number }>
}

export interface EvalCompare {
  summaries: Record<string, EvalSystemSummary>
  c_vs_crag: {
    fp_before: number
    fp_after: number
    fp_cost_before: number
    fp_cost_after: number
    precision_before: number | null
    precision_after: number | null
    recall_before: number | null
    recall_after: number | null
    f1_before: number | null
    f1_after: number | null
    fp_cost_weight: number
  } | null
}

export interface FindingsResponse {
  items: FindingListItem[]
  total: number
}

// ---- Audit log ----

export interface AuditEvent {
  seq: number
  ts: string
  actor: string
  event: string
  object_type: string | null
  object_id: string | null
  metadata_json?: Record<string, unknown> | null
  hash: string
}

export interface AuditLogResponse {
  events: AuditEvent[]
  total: number
  chain_ok: boolean
}

export interface AuditVerifyResponse {
  ok: boolean
  error: string | null
  n_events: number
}

// ---- Evaluation ----

export interface DefectClassMetrics {
  defect_class: DefectClass
  precision: number
  recall: number
  f1: number
  n_true_positive: number
  n_false_positive: number
  n_false_negative: number
}

export interface EvalReport {
  run_at: string
  overall_f1: number
  overall_precision: number
  overall_recall: number
  per_class: DefectClassMetrics[]
}

// ---- System status ----

export interface SystemStatus {
  api: string // 'ok'
  db: string // 'ok' | 'error'
  gateway: string // 'ok' | 'chaos' | 'error' | 'unreachable'
  llm: string // 'ok' | 'degraded' | 'unavailable'
  worker: { last_job_at: string | null; pending_jobs: number }
}

// ---- Settings ----

export interface Settings {
  advisory_threshold: number
  verify_threshold: number
  gateway_mode: string
  chaos_llm: boolean
  chaos_gateway: boolean
  chaos_enabled: boolean // legacy: llm || gateway
}

// ---- Verification SSE ----

export interface VerificationSSEEvent {
  status: VerificationStatus | 'RUNNING'
  message: string
}
