'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getFinding, dismissFinding, escalateFinding } from '@/lib/api'
import { SeverityBadge } from '@/components/SeverityBadge'
import { StateBadge } from '@/components/StateBadge'
import { FindingDetailTabs } from '@/components/FindingDetailTabs'
import type { Finding } from '@/lib/types'

export default function FindingDetailPage() {
  const params = useParams()
  const findingId = params.id as string
  const [finding, setFinding] = useState<Finding | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  const mapFinding = (raw: any): Finding => ({
    ...raw,
    title: raw.defect_class?.replace(/_/g, ' ') ?? '',
    file_path: raw.file ?? null,
    line_number: raw.start_line ?? null,
    static_confidence: raw.confidence ?? null,
    exposure_kind: raw.exposure_measured_paise != null ? 'MEASURED' : raw.exposure_estimated_paise != null ? 'ESTIMATED' : null,
    exposure_paise: raw.exposure_measured_paise ?? raw.exposure_estimated_paise ?? null,
    assumptions: raw.exposure_assumptions_json ? JSON.stringify(raw.exposure_assumptions_json, null, 2) : null,
    verification_results: raw.verification_results ?? [],
    remediations: raw.remediations ?? [],
    code_context: raw.code_context ?? null,
  })

  const refresh = useCallback(async () => {
    if (!findingId) return
    try {
      const raw = await getFinding(findingId)
      setFinding(mapFinding(raw))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load finding')
    } finally {
      setLoading(false)
    }
  }, [findingId])

  useEffect(() => { refresh() }, [refresh])

  const handleDismiss = async () => {
    setActionLoading(true)
    setActionError(null)
    try {
      await dismissFinding(findingId, 'Dismissed by user')
      await refresh()
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Failed to dismiss')
    } finally {
      setActionLoading(false)
    }
  }

  const handleEscalate = async () => {
    setActionLoading(true)
    setActionError(null)
    try {
      await escalateFinding(findingId)
      await refresh()
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Failed to escalate')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return (
      <div>
        <Link href="/findings" style={{ color: '#6B7280', fontSize: 13, textDecoration: 'none' }}>
          Back to findings
        </Link>
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ height: 80, background: '#F3F4F6', borderRadius: 6 }} />
          <div style={{ height: 400, background: '#F3F4F6', borderRadius: 6 }} />
        </div>
      </div>
    )
  }

  if (error || !finding) {
    return (
      <div>
        <Link href="/findings" style={{ color: '#6B7280', fontSize: 13, textDecoration: 'none' }}>
          Back to findings
        </Link>
        <div
          className="panel"
          style={{ marginTop: 16, padding: '14px 16px', color: '#B42318', fontSize: 13 }}
        >
          {error ?? 'Finding not found.'}
        </div>
      </div>
    )
  }

  const btnStyle = (variant: 'primary' | 'default') => ({
    padding: '6px 12px',
    background: variant === 'primary' ? '#111827' : '#fff',
    color: variant === 'primary' ? '#fff' : '#374151',
    border: variant === 'primary' ? 'none' : '1px solid #E5E7EB',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 500 as const,
    cursor: actionLoading ? 'not-allowed' as const : 'pointer' as const,
    opacity: actionLoading ? 0.6 : 1,
  })

  return (
    <div style={{ maxWidth: 960 }}>
      {/* Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 13 }}>
        <Link href="/findings" style={{ color: '#6B7280', textDecoration: 'none' }}>Findings</Link>
        <span style={{ color: '#D1D5DB' }}>/</span>
        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#374151' }}>
          {findingId.slice(0, 8)}
        </span>
      </div>

      {/* Header card */}
      <div className="panel" style={{ padding: '16px 20px', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* Badges */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
              <SeverityBadge severity={finding.severity} />
              <StateBadge state={finding.state} size="sm" />
              <span
                style={{
                  fontSize: 11,
                  color: '#6B7280',
                  border: '1px solid #E5E7EB',
                  borderRadius: 4,
                  padding: '1px 6px',
                  fontWeight: 500,
                }}
              >
                {finding.detector_source}
              </span>
              <span
                style={{
                  fontSize: 11,
                  color: '#6B7280',
                  border: '1px solid #E5E7EB',
                  borderRadius: 4,
                  padding: '1px 6px',
                }}
              >
                {finding.defect_class.replace(/_/g, ' ')}
              </span>
              {finding.detector_source === 'LLM' && finding.state !== 'VERIFIED' && (
                <span
                  style={{
                    fontSize: 11,
                    color: '#92400E',
                    background: '#FFFBEB',
                    border: '1px solid #FDE68A',
                    borderRadius: 4,
                    padding: '1px 6px',
                    fontWeight: 600,
                  }}
                >
                  AI finding — unverified
                </span>
              )}
            </div>

            {/* Title */}
            <div style={{ fontSize: 15, fontWeight: 600, color: '#111827', marginBottom: 6 }}>
              {finding.title}
            </div>

            {/* File location */}
            {finding.file_path && (
              <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#9CA3AF' }}>
                {finding.file_path}{finding.line_number ? `:${finding.line_number}` : ''}
              </div>
            )}
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, flexShrink: 0, alignItems: 'flex-start' }}>
            {finding.state !== 'DISMISSED' && (
              <button onClick={handleDismiss} disabled={actionLoading} style={btnStyle('default')}>
                Dismiss
              </button>
            )}
            {finding.state === 'ADVISORY' && (
              <button onClick={handleEscalate} disabled={actionLoading} style={btnStyle('primary')}>
                Escalate
              </button>
            )}
          </div>
        </div>

        {actionError && (
          <div style={{ marginTop: 10, fontSize: 12, color: '#B42318' }}>{actionError}</div>
        )}
      </div>

      {/* 5-tab detail */}
      <FindingDetailTabs finding={finding} />
    </div>
  )
}
