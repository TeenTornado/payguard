'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { listFindings } from '@/lib/api'
import type { FindingListItem, Severity, FindingState, DefectClass } from '@/lib/types'
import { SeverityBadge } from './SeverityBadge'
import { StateBadge } from './StateBadge'
import { ExposureBadge } from './ExposureBadge'
import { formatDate } from '@/lib/format'

interface Props {
  scanId?: string
  initialState?: FindingState
  showFilters?: boolean
}

const SEVERITY_OPTIONS: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const STATE_OPTIONS: FindingState[] = ['ADVISORY', 'QUEUED_FOR_VERIFICATION', 'VERIFIED', 'UNVERIFIED', 'EXCEPTION', 'DISMISSED']
const CLASS_OPTIONS: DefectClass[] = ['DUPLICATE_PAYMENT', 'WEBHOOK_INTEGRITY', 'AMOUNT_CURRENCY', 'SUSPICIOUS_CONTENT']

export function FindingsTable({ scanId, initialState, showFilters = true }: Props) {
  const [items, setItems] = useState<FindingListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [severity, setSeverity] = useState<string>('')
  const [state, setState] = useState<string>(initialState ?? '')
  const [defectClass, setDefectClass] = useState<string>('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listFindings({
        scan_id: scanId,
        severity: severity || undefined,
        state: state || undefined,
        defect_class: defectClass || undefined,
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load findings')
    } finally {
      setLoading(false)
    }
  }, [scanId, severity, state, defectClass])

  useEffect(() => {
    load()
  }, [load])

  const selectStyle = {
    padding: '5px 8px',
    border: '1px solid #E5E7EB',
    borderRadius: 6,
    fontSize: 12,
    color: '#374151',
    background: '#fff',
    cursor: 'pointer',
    outline: 'none',
  }

  return (
    <div>
      {showFilters && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} style={selectStyle}>
            <option value="">All severities</option>
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select value={state} onChange={(e) => setState(e.target.value)} style={selectStyle}>
            <option value="">All states</option>
            {STATE_OPTIONS.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <select value={defectClass} onChange={(e) => setDefectClass(e.target.value)} style={selectStyle}>
            <option value="">All classes</option>
            {CLASS_OPTIONS.map((c) => (
              <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <span style={{ fontSize: 12, color: '#9CA3AF', marginLeft: 4 }}>
            {total} finding{total !== 1 ? 's' : ''}
          </span>
        </div>
      )}

      <div className="panel" style={{ overflow: 'hidden' }}>
        {error && (
          <div style={{ padding: '12px 16px', color: '#B42318', fontSize: 13 }}>
            Error: {error}
          </div>
        )}

        {loading ? (
          <div style={{ padding: 16 }}>
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                style={{
                  height: 32,
                  background: '#F3F4F6',
                  borderRadius: 4,
                  marginBottom: 4,
                  opacity: 1 - i * 0.15,
                }}
              />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            No findings match the current filters.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Title</th>
                <th>Class</th>
                <th>State</th>
                <th>Source</th>
                <th>Exposure</th>
                <th>File</th>
                <th>Detected</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td><SeverityBadge severity={item.severity} size="sm" /></td>
                  <td>
                    <Link
                      href={`/findings/${item.id}`}
                      style={{
                        color: '#111827',
                        textDecoration: 'none',
                        fontWeight: 500,
                        fontSize: 13,
                      }}
                    >
                      {item.title}
                    </Link>
                  </td>
                  <td style={{ color: '#6B7280', fontSize: 12 }}>
                    {item.defect_class.replace(/_/g, ' ')}
                  </td>
                  <td><StateBadge state={item.state} size="sm" /></td>
                  <td style={{ color: '#6B7280', fontSize: 12 }}>
                    {item.detector_source}
                  </td>
                  <td>
                    {item.exposure_kind && item.exposure_paise != null ? (
                      <ExposureBadge kind={item.exposure_kind} paise={item.exposure_paise} />
                    ) : (
                      <span style={{ color: '#D1D5DB' }}>—</span>
                    )}
                  </td>
                  <td>
                    {item.file_path ? (
                      <span
                        style={{
                          fontFamily: 'JetBrains Mono, monospace',
                          fontSize: 11,
                          color: '#6B7280',
                          maxWidth: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          display: 'inline-block',
                        }}
                      >
                        {item.file_path}
                        {item.line_number ? `:${item.line_number}` : ''}
                      </span>
                    ) : (
                      <span style={{ color: '#D1D5DB' }}>—</span>
                    )}
                  </td>
                  <td style={{ color: '#9CA3AF', fontSize: 12, whiteSpace: 'nowrap' }}>
                    {formatDate(item.created_at)}
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
