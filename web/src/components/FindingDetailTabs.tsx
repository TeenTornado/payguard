'use client'

import { useState, useEffect } from 'react'
import type { Finding, VerificationStatus, Remediation } from '@/lib/types'
import { CodeViewer } from './CodeViewer'
import { StateBadge } from './StateBadge'
import { ExposureBadge } from './ExposureBadge'
import {
  verifyFinding,
  verificationStream,
  proposeRemediation,
  approveRemediation,
  rejectRemediation,
} from '@/lib/api'
import { formatDate, formatPaise } from '@/lib/format'

type Tab = 'evidence' | 'ai' | 'verification' | 'exposure' | 'fix'

const TABS: { id: Tab; label: string }[] = [
  { id: 'evidence', label: 'Deterministic evidence' },
  { id: 'ai', label: 'AI reasoning' },
  { id: 'verification', label: 'Verification' },
  { id: 'exposure', label: 'Exposure' },
  { id: 'fix', label: 'Fix' },
]

interface Props {
  finding: Finding
  onRefresh?: () => void
}

export function FindingDetailTabs({ finding, onRefresh }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('evidence')

  const tabBarStyle = {
    display: 'flex',
    borderBottom: '1px solid #E5E7EB',
    gap: 0,
    marginBottom: 0,
    background: '#fff',
  }

  const tabStyle = (id: Tab) => ({
    padding: '10px 16px',
    fontSize: 13,
    fontWeight: activeTab === id ? 500 : 400,
    color: activeTab === id ? '#111827' : '#6B7280',
    borderBottom: activeTab === id ? '2px solid #111827' : '2px solid transparent',
    cursor: 'pointer',
    background: 'none',
    border: 'none',
    borderRadius: 0,
    marginBottom: -1,
  })

  return (
    <div className="panel" style={{ overflow: 'hidden' }}>
      <div style={tabBarStyle}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={tabStyle(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: 20 }}>
        {activeTab === 'evidence' && <EvidenceTab finding={finding} />}
        {activeTab === 'ai' && <AIReasoningTab finding={finding} />}
        {activeTab === 'verification' && <VerificationTab finding={finding} onRefresh={onRefresh} />}
        {activeTab === 'exposure' && <ExposureTab finding={finding} />}
        {activeTab === 'fix' && <FixTab finding={finding} />}
      </div>
    </div>
  )
}

// ---- Evidence Tab ----

function EvidenceTab({ finding }: { finding: Finding }) {
  const ctx = finding.code_context
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {finding.rule_ids && finding.rule_ids.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 8 }}>Rule IDs</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {finding.rule_ids.map((r) => (
              <span
                key={r}
                style={{
                  fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 11,
                  padding: '2px 8px',
                  background: '#F3F4F6',
                  border: '1px solid #E5E7EB',
                  borderRadius: 4,
                  color: '#374151',
                }}
              >
                {r}
              </span>
            ))}
          </div>
        </div>
      )}

      {finding.static_confidence != null && (
        <div>
          <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 4 }}>
            Static confidence
          </div>
          <div style={{ fontSize: 20, fontFamily: 'JetBrains Mono, monospace', fontWeight: 600, color: '#111827' }}>
            {(finding.static_confidence * 100).toFixed(1)}%
          </div>
        </div>
      )}

      {ctx ? (
        <div>
          <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 8 }}>Code evidence</div>
          <CodeViewer
            lines={ctx.lines}
            highlightStart={ctx.highlight_start}
            highlightEnd={ctx.highlight_end}
            file={ctx.file}
          />
        </div>
      ) : (
        <div style={{ color: '#9CA3AF', fontSize: 13 }}>No code context available for this finding.</div>
      )}
    </div>
  )
}

// ---- AI Reasoning Tab ----

function AIReasoningTab({ finding }: { finding: Finding }) {
  const verified = finding.state === 'VERIFIED'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div
        style={{
          padding: '10px 14px',
          background: verified ? '#ECFDF3' : '#FFFBEB',
          border: `1px solid ${verified ? '#A6F4C5' : '#FDE68A'}`,
          borderRadius: 6,
          fontSize: 12,
          color: verified ? '#067647' : '#92400E',
          fontWeight: 500,
        }}
      >
        {verified
          ? 'The verifier confirmed this finding in the sandbox — the AI hypothesis was proven.'
          : 'AI finding — unverified. The LLM proposes; the verifier decides. Do not act on this alone.'}
      </div>

      {finding.grounding && (
        <div style={{ border: '1px solid #E5E7EB', borderRadius: 6, padding: '12px 14px', background: '#F9FAFB' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
            Grounded on retrieved Razorpay knowledge
          </div>
          {finding.grounding.cited_rule && (
            <div style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#1D4ED8', fontWeight: 600 }}>
                {finding.grounding.cited_rule.id}
              </span>
              <span style={{ fontSize: 13, color: '#374151', marginLeft: 6 }}>
                {finding.grounding.cited_rule.title}
              </span>
              <div style={{ fontSize: 12, color: '#6B7280', marginTop: 4, lineHeight: 1.5 }}>
                {finding.grounding.cited_rule.text.slice(0, 280)}
              </div>
            </div>
          )}
          <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, marginBottom: 4 }}>
            Retrieved labeled examples
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {finding.grounding.references
              .filter((r) => r.tier === 'EXAMPLE')
              .slice(0, 4)
              .map((r) => (
                <div key={r.id} style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#6B7280' }}>
                  <span style={{ color: r.kind === 'SAFE_PATTERN' ? '#067647' : '#B42318' }}>{r.kind}</span>
                  {' · '}{r.sample_id}
                  {r.hard_negative && <span style={{ color: '#B54708' }}> · hard-negative</span>}
                </div>
              ))}
          </div>
        </div>
      )}

      {finding.llm_reasoning ? (
        <div
          style={{
            fontSize: 13,
            color: '#374151',
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
            fontFamily: 'inherit',
          }}
        >
          {finding.llm_reasoning}
        </div>
      ) : (
        <div style={{ color: '#9CA3AF', fontSize: 13 }}>
          No AI reasoning recorded for this finding.
        </div>
      )}
    </div>
  )
}

// ---- Verification Tab ----

function VerificationTab({ finding, onRefresh }: { finding: Finding; onRefresh?: () => void }) {
  const [verifying, setVerifying] = useState(false)
  const [streamMessages, setStreamMessages] = useState<string[]>([])
  const [streamStatus, setStreamStatus] = useState<VerificationStatus | 'RUNNING' | null>(null)
  const [verdict, setVerdict] = useState<{
    status: string
    measured_impact_paise?: number | null
    proof_summary?: string | null
    observed_behavior?: string | null
    error_code?: string | null
    attempts?: number | null
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const latestVerification =
    finding.verification_results.length > 0
      ? finding.verification_results[finding.verification_results.length - 1]
      : null

  const handleVerify = async () => {
    setVerifying(true)
    setStreamMessages([])
    setStreamStatus('RUNNING')
    setVerdict(null)
    setError(null)

    try {
      const { verification_id } = await verifyFinding(finding.id)
      const es = verificationStream(verification_id)

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.message) {
            setStreamMessages((prev) => [...prev, data.message])
          }
          if (data.status) {
            setStreamStatus(data.status)
          }
          if (data.done) {
            setVerdict({
              status: data.status,
              measured_impact_paise: data.measured_impact_paise,
              proof_summary: data.proof_summary,
              observed_behavior: data.observed_behavior,
              error_code: data.error_code,
              attempts: data.attempts,
            })
            es.close()
            setVerifying(false)
            onRefresh?.()
          }
        } catch {
          // ignore
        }
      }

      es.onerror = () => {
        es.close()
        setVerifying(false)
        setStreamStatus(null)
        setError('Verification stream disconnected.')
      }
    } catch (e: unknown) {
      setVerifying(false)
      setStreamStatus(null)
      setError(e instanceof Error ? e.message : 'Failed to start verification')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Prior verifications */}
      {finding.verification_results.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 10 }}>
            Prior verifications
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {finding.verification_results.map((v) => (
              <div
                key={v.id}
                style={{
                  padding: '10px 14px',
                  background: '#F9FAFB',
                  border: '1px solid #E5E7EB',
                  borderRadius: 6,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <StateBadge state={v.status} size="sm" />
                  {v.scenario_id && (
                    <span style={{ fontSize: 11, color: '#6B7280', fontFamily: 'JetBrains Mono, monospace' }}>
                      {v.scenario_id}
                    </span>
                  )}
                  {v.error_code && (
                    <span
                      style={{
                        fontSize: 11,
                        color: '#B42318',
                        fontFamily: 'JetBrains Mono, monospace',
                        border: '1px solid #FECACA',
                        borderRadius: 4,
                        padding: '0 5px',
                      }}
                    >
                      {v.error_code}
                    </span>
                  )}
                  {v.attempts != null && v.attempts > 1 && (
                    <span style={{ fontSize: 11, color: '#B54708' }}>{v.attempts} attempts</span>
                  )}
                  {(v.finished_at ?? v.started_at ?? v.created_at) && (
                    <span style={{ fontSize: 12, color: '#9CA3AF' }}>
                      {formatDate((v.finished_at ?? v.started_at ?? v.created_at)!)}
                    </span>
                  )}
                </div>
                {(v.observed_behavior || v.message) && (
                  <div style={{ fontSize: 13, color: '#374151' }}>{v.observed_behavior ?? v.message}</div>
                )}
                {v.status === 'VERIFIED' && v.measured_impact_paise != null ? (
                  <div style={{ fontSize: 12, color: '#067647', fontWeight: 600 }}>
                    MEASURED impact: {formatPaise(v.measured_impact_paise)}
                  </div>
                ) : v.status === 'ERROR' ? (
                  <div style={{ fontSize: 12, color: '#B42318' }}>
                    No MEASURED amount — verification did not complete.
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live stream output */}
      {(streamMessages.length > 0 || streamStatus === 'RUNNING') && (
        <div
          style={{
            padding: '12px 14px',
            background: '#0F172A',
            borderRadius: 6,
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          {streamMessages.map((msg, i) => (
            <div key={i} style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>
              {msg}
            </div>
          ))}
          {streamStatus === 'RUNNING' && (
            <div style={{ fontSize: 12, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>
              Running...
            </div>
          )}
        </div>
      )}

      {verdict && (
        <div
          style={{
            padding: '14px 16px',
            borderRadius: 8,
            border: `1px solid ${verdict.status === 'VERIFIED' ? '#A6F4C5' : verdict.status === 'ERROR' ? '#FECACA' : '#E5E7EB'}`,
            background: verdict.status === 'VERIFIED' ? '#ECFDF3' : verdict.status === 'ERROR' ? '#FEF3F2' : '#F9FAFB',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <StateBadge state={verdict.status} />
            <span style={{ fontSize: 12, color: '#6B7280' }}>tier EMULATED</span>
            {verdict.attempts != null && verdict.attempts > 1 && (
              <span style={{ fontSize: 12, color: '#B54708' }}>{verdict.attempts} gateway attempts</span>
            )}
            {verdict.error_code && (
              <span style={{ fontSize: 11, color: '#B42318', fontFamily: 'JetBrains Mono, monospace' }}>
                {verdict.error_code}
              </span>
            )}
          </div>
          {verdict.status === 'VERIFIED' && verdict.measured_impact_paise != null && (
            <div style={{ fontSize: 20, fontWeight: 700, color: '#067647', fontFamily: 'JetBrains Mono, monospace' }}>
              MEASURED impact {formatPaise(verdict.measured_impact_paise)}
            </div>
          )}
          {verdict.status === 'ERROR' && (
            <div style={{ fontSize: 13, color: '#B42318' }}>
              Verification could not complete — no MEASURED amount was written.
            </div>
          )}
          {(verdict.proof_summary || verdict.observed_behavior) && (
            <div style={{ fontSize: 13, color: '#374151', lineHeight: 1.5 }}>
              {verdict.proof_summary || verdict.observed_behavior}
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: '8px 12px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, fontSize: 13, color: '#B42318' }}>
          {error}
        </div>
      )}

      <button
        onClick={handleVerify}
        disabled={verifying}
        style={{
          alignSelf: 'flex-start',
          padding: '8px 16px',
          background: verifying ? '#F3F4F6' : '#111827',
          color: verifying ? '#9CA3AF' : '#fff',
          border: 'none',
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 500,
          cursor: verifying ? 'not-allowed' : 'pointer',
        }}
      >
        {verifying ? 'Verifying…' : 'Verify'}
      </button>
    </div>
  )
}

// ---- Exposure Tab ----

function ExposureTab({ finding }: { finding: Finding }) {
  if (!finding.exposure_kind || finding.exposure_paise == null) {
    return (
      <div style={{ color: '#9CA3AF', fontSize: 13 }}>
        No exposure data recorded for this finding.
      </div>
    )
  }

  const verified = (finding.verification_results || []).find((v) => v.status === 'VERIFIED')
  const tier = verified?.tier ?? 'EMULATED'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <ExposureBadge kind={finding.exposure_kind} paise={finding.exposure_paise} />
      </div>

      {finding.exposure_kind === 'MEASURED' ? (
        <div
          style={{
            padding: '12px 14px',
            background: '#ECFDF3',
            border: '1px solid #A6F4C5',
            borderRadius: 6,
            fontSize: 13,
            color: '#067647',
            lineHeight: 1.6,
          }}
        >
          <strong>Measured</strong> — this amount was observed by driving the running target in
          the sandbox and counting a real duplicate fulfillment (tier {tier}). It is not an
          estimate.
        </div>
      ) : (
        <>
          <div
            style={{
              padding: '12px 14px',
              background: '#FFFAEB',
              border: '1px solid #FEF3C7',
              borderRadius: 6,
              fontSize: 13,
              color: '#92400E',
              lineHeight: 1.6,
            }}
          >
            <strong>Estimated</strong>, not measured — a per-class heuristic for a{' '}
            {finding.defect_class?.replace(/_/g, ' ').toLowerCase()} finding. Run <em>Verify</em> to
            replace this with a measured amount. This is potential exposure, not money saved.
          </div>
          {finding.assumptions && (
            <div>
              <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 8 }}>
                Assumptions
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: '12px 14px',
                  background: '#F9FAFB',
                  border: '1px solid #E5E7EB',
                  borderRadius: 6,
                  fontSize: 12,
                  color: '#374151',
                  fontFamily: 'JetBrains Mono, monospace',
                  overflowX: 'auto',
                }}
              >
                {finding.assumptions}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---- Fix Tab ----

function FixTab({ finding }: { finding: Finding }) {
  const [proposing, setProposing] = useState(false)
  const [remediation, setRemediation] = useState<Remediation | null>(
    finding.remediations.length > 0 ? finding.remediations[finding.remediations.length - 1] : null
  )
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handlePropose = async () => {
    setProposing(true)
    setError(null)
    try {
      const r = await proposeRemediation(finding.id)
      setRemediation(r)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to propose fix')
    } finally {
      setProposing(false)
    }
  }

  const handleApprove = async () => {
    if (!remediation) return
    setActionLoading(true)
    try {
      await approveRemediation(remediation.id)
      setRemediation((prev) => prev ? { ...prev, status: 'APPROVED' } : prev)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to approve')
    } finally {
      setActionLoading(false)
    }
  }

  const handleReject = async () => {
    if (!remediation) return
    setActionLoading(true)
    try {
      await rejectRemediation(remediation.id)
      setRemediation((prev) => prev ? { ...prev, status: 'REJECTED' } : prev)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to reject')
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {error && (
        <div style={{ padding: '8px 12px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, fontSize: 13, color: '#B42318' }}>
          {error}
        </div>
      )}

      {!remediation ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13, color: '#6B7280' }}>
            No fix proposed yet. Click below to generate an AI-proposed remediation diff.
          </div>
          <button
            onClick={handlePropose}
            disabled={proposing}
            style={{
              alignSelf: 'flex-start',
              padding: '8px 16px',
              background: proposing ? '#F3F4F6' : '#111827',
              color: proposing ? '#9CA3AF' : '#fff',
              border: 'none',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 500,
              cursor: proposing ? 'not-allowed' : 'pointer',
            }}
          >
            {proposing ? 'Proposing...' : 'Propose fix'}
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#6B7280' }}>Status:</span>
            <StateBadge state={remediation.status} size="sm" />
          </div>

          {/* Rationale */}
          {remediation.rationale && (
            <div>
              <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 8 }}>Rationale</div>
              <div style={{ fontSize: 13, color: '#374151', lineHeight: 1.6 }}>{remediation.rationale}</div>
            </div>
          )}

          {/* Diff */}
          {remediation.diff && (
            <div>
              <div style={{ fontSize: 12, color: '#6B7280', fontWeight: 500, marginBottom: 8 }}>Diff</div>
              <div
                style={{
                  background: '#0F172A',
                  borderRadius: 6,
                  padding: '12px 16px',
                  fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 12,
                  lineHeight: 1.6,
                  overflowX: 'auto',
                  border: '1px solid #1E293B',
                }}
              >
                {remediation.diff.split('\n').map((line, i) => {
                  let color = '#CBD5E1'
                  if (line.startsWith('+')) color = '#86EFAC'
                  else if (line.startsWith('-')) color = '#FCA5A5'
                  else if (line.startsWith('@@')) color = '#67E8F9'
                  return (
                    <div key={i} style={{ color, whiteSpace: 'pre' }}>
                      {line}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Actions */}
          {remediation.status === 'PENDING' && (
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleApprove}
                disabled={actionLoading}
                style={{
                  padding: '8px 16px',
                  background: '#067647',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: actionLoading ? 'not-allowed' : 'pointer',
                }}
              >
                Approve
              </button>
              <button
                onClick={handleReject}
                disabled={actionLoading}
                style={{
                  padding: '8px 16px',
                  background: '#fff',
                  color: '#B42318',
                  border: '1px solid #FECACA',
                  borderRadius: 6,
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: actionLoading ? 'not-allowed' : 'pointer',
                }}
              >
                Reject
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
