'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { listFindings, dismissFinding, verifyFinding } from '@/lib/api'
import { SeverityBadge } from '@/components/SeverityBadge'
import { StateBadge } from '@/components/StateBadge'
import { ExposureBadge } from '@/components/ExposureBadge'
import { formatDate } from '@/lib/format'
import type { FindingListItem } from '@/lib/types'

export default function ExceptionQueuePage() {
  const [items, setItems] = useState<FindingListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Fetch EXCEPTION + ADVISORY findings (non-VERIFIED, non-DISMISSED)
      const [exc, adv] = await Promise.all([
        listFindings({ state: 'EXCEPTION' }),
        listFindings({ state: 'ADVISORY' }),
      ])
      setItems([...exc.items, ...adv.items])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load exception queue')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleDismiss = async (id: string) => {
    setActionLoading(id)
    try {
      await dismissFinding(id, 'Dismissed from exception queue')
      await refresh()
    } finally {
      setActionLoading(null)
    }
  }

  const handleVerify = async (id: string) => {
    setActionLoading(id)
    try {
      await verifyFinding(id)
      await refresh()
    } finally {
      setActionLoading(null)
    }
  }

  const btnStyle = (id: string, variant: 'primary' | 'default') => ({
    padding: '4px 10px',
    background: variant === 'primary' ? '#111827' : '#fff',
    color: variant === 'primary' ? '#fff' : '#374151',
    border: variant === 'primary' ? 'none' : '1px solid #E5E7EB',
    borderRadius: 5,
    fontSize: 12,
    cursor: actionLoading === id ? 'not-allowed' : 'pointer',
    fontWeight: 500 as const,
    opacity: actionLoading === id ? 0.6 : 1,
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <span style={{ fontSize: 20, fontWeight: 600, color: '#111827' }}>Exception Queue</span>
        <span style={{ fontSize: 12, color: '#9CA3AF' }}>{items.length} items</span>
      </div>

      <div className="panel" style={{ overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 16 }}>
            {[...Array(5)].map((_, i) => (
              <div key={i} style={{ height: 32, background: '#F3F4F6', borderRadius: 4, marginBottom: 4, opacity: 1 - i * 0.15 }} />
            ))}
          </div>
        ) : error ? (
          <div style={{ padding: '14px 16px', color: '#B42318', fontSize: 13 }}>Error: {error}</div>
        ) : items.length === 0 ? (
          <div style={{ padding: '32px 16px', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            Exception queue is empty — no items needing attention.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Finding</th>
                <th>Severity</th>
                <th>State</th>
                <th>Class</th>
                <th>File</th>
                <th>Exposure</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id}>
                  <td>
                    <Link
                      href={`/findings/${f.id}`}
                      style={{
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 11,
                        color: '#1D4ED8',
                        textDecoration: 'none',
                        display: 'block',
                        maxWidth: 200,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {f.title}
                    </Link>
                  </td>
                  <td><SeverityBadge severity={f.severity} size="sm" /></td>
                  <td><StateBadge state={f.state} size="sm" /></td>
                  <td style={{ fontSize: 12, color: '#6B7280' }}>
                    {f.defect_class.replace(/_/g, ' ')}
                  </td>
                  <td>
                    {f.file_path ? (
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#9CA3AF' }}>
                        {f.file_path.split('/').pop()}
                        {f.line_number ? `:${f.line_number}` : ''}
                      </span>
                    ) : (
                      <span style={{ color: '#D1D5DB' }}>—</span>
                    )}
                  </td>
                  <td>
                    {f.exposure_kind && f.exposure_paise != null ? (
                      <ExposureBadge kind={f.exposure_kind} paise={f.exposure_paise} />
                    ) : (
                      <span style={{ color: '#D1D5DB' }}>—</span>
                    )}
                  </td>
                  <td style={{ fontSize: 12, color: '#9CA3AF', whiteSpace: 'nowrap' }}>
                    {formatDate(f.created_at)}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        onClick={() => handleVerify(f.id)}
                        disabled={!!actionLoading}
                        style={btnStyle(f.id, 'primary')}
                      >
                        Verify
                      </button>
                      <button
                        onClick={() => handleDismiss(f.id)}
                        disabled={!!actionLoading}
                        style={btnStyle(f.id, 'default')}
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
