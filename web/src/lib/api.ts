import type {
  Scan,
  ScanListItem,
  PreflightResult,
  Finding,
  FindingListItem,
  FindingsResponse,
  AuditLogResponse,
  AuditVerifyResponse,
  EvalReport,
  SystemStatus,
  Settings,
  VerificationResult,
  Remediation,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ---- Scans ----

export function listScans(): Promise<ScanListItem[]> {
  return apiFetch<ScanListItem[]>('/scans')
}

export function getScan(id: string): Promise<Scan> {
  return apiFetch<Scan>(`/scans/${id}`)
}

export function createScan(repo_path: string): Promise<{ id: string; state: string; started_at: string }> {
  return apiFetch('/scans', {
    method: 'POST',
    body: JSON.stringify({ repo_path }),
  })
}

export function preflightScan(repo_path: string): Promise<PreflightResult> {
  return apiFetch('/scans/preflight', {
    method: 'POST',
    body: JSON.stringify({ repo_path }),
  })
}

/** Returns an EventSource for scan state SSE. Caller must close it. */
export function scanEvents(id: string): EventSource {
  return new EventSource(`${BASE}/scans/${id}/events`)
}

// ---- Findings ----

export interface FindingsFilter {
  scan_id?: string
  state?: string
  severity?: string
  defect_class?: string
}

export function listFindings(filter: FindingsFilter = {}): Promise<FindingsResponse> {
  const params = new URLSearchParams()
  if (filter.scan_id) params.set('scan_id', filter.scan_id)
  if (filter.state) params.set('state', filter.state)
  if (filter.severity) params.set('severity', filter.severity)
  if (filter.defect_class) params.set('defect_class', filter.defect_class)
  const qs = params.toString()
  return apiFetch<FindingsResponse>(`/findings${qs ? `?${qs}` : ''}`)
}

export function getFinding(id: string): Promise<Finding> {
  return apiFetch<Finding>(`/findings/${id}`)
}

export function verifyFinding(id: string): Promise<{ verification_id: string }> {
  return apiFetch(`/findings/${id}/verify`, {
    method: 'POST',
    body: JSON.stringify({ actor: 'HUMAN' }),
  })
}

export function dismissFinding(id: string, reason: string): Promise<{ ok: boolean }> {
  return apiFetch(`/findings/${id}/dismiss`, {
    method: 'POST',
    body: JSON.stringify({ reason, actor: 'HUMAN' }),
  })
}

export function escalateFinding(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/findings/${id}/escalate`, {
    method: 'POST',
    body: JSON.stringify({ actor: 'HUMAN' }),
  })
}

export function proposeRemediation(id: string): Promise<Remediation> {
  return apiFetch<Remediation>(`/findings/${id}/remediation/propose`, {
    method: 'POST',
    body: JSON.stringify({ actor: 'HUMAN' }),
  })
}

/** Returns an EventSource for verification SSE. Caller must close it. */
export function verificationStream(verificationId: string): EventSource {
  return new EventSource(`${BASE}/verifications/${verificationId}/stream`)
}

// ---- Remediations ----

export function approveRemediation(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/remediations/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ actor: 'HUMAN' }),
  })
}

export function rejectRemediation(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/remediations/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ actor: 'HUMAN' }),
  })
}

// ---- Audit Log ----

export function getAuditLog(limit = 50): Promise<AuditLogResponse> {
  return apiFetch<AuditLogResponse>(`/audit?limit=${limit}`)
}

export function verifyAuditChain(): Promise<AuditVerifyResponse> {
  return apiFetch<AuditVerifyResponse>('/audit/verify', { method: 'POST' })
}

// ---- Evaluation ----

export function getLatestEval(): Promise<EvalReport | null> {
  return apiFetch<EvalReport | null>('/eval/latest')
}

// ---- System ----

export function getSystemStatus(): Promise<SystemStatus> {
  return apiFetch<SystemStatus>('/system/status')
}

// ---- Settings ----

export function getSettings(): Promise<Settings> {
  return apiFetch<Settings>('/settings')
}

export function updateSettings(patch: Partial<Settings>): Promise<Settings> {
  return apiFetch<Settings>('/settings', {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}
