'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { listScans, getSystemStatus } from '@/lib/api'
import type { ScanListItem, SystemStatus } from '@/lib/types'
import { KpiCard } from '@/components/KpiCard'
import { StateBadge } from '@/components/StateBadge'
import { formatDate, formatDuration } from '@/lib/format'

// Map a backend status string to a traffic-light colour.
function statusColor(val: string): string {
  if (val === 'ok' || val === 'idle') return '#067647' // green
  if (val === 'chaos' || val === 'degraded' || val.endsWith('queued')) return '#B54708' // amber
  return '#B42318' // red: error / unreachable / unavailable
}

export default function OverviewPage() {
  const [scans, setScans] = useState<ScanListItem[]>([])
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [s, sys] = await Promise.all([listScans(), getSystemStatus()])
        setScans(s)
        setStatus(sys)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load overview')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const totalFindings = scans.reduce((acc, s) => acc + (s.n_findings ?? 0), 0)
  const doneScans = scans.filter((s) => s.state === 'DONE').length
  const activeScans = scans.filter((s) => s.state !== 'DONE' && s.state !== 'FAILED').length
  const recentScans = scans.slice(0, 10)

  if (loading) {
    return (
      <div>
        <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Overview</div>
        <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} style={{ width: 160, height: 80, background: '#F3F4F6', borderRadius: 6 }} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Overview</div>

      {error && (
        <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#B42318' }}>
          Cannot connect to API: {error}
        </div>
      )}

      {/* System status strip */}
      {status && (
        <div
          style={{
            display: 'flex',
            gap: 16,
            padding: '8px 14px',
            background: '#fff',
            border: '1px solid #E5E7EB',
            borderRadius: 6,
            marginBottom: 20,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 12, color: '#6B7280', fontWeight: 500 }}>System</span>
          {([
            ['api', status.api],
            ['db', status.db],
            ['gateway', status.gateway],
            ['llm', status.llm],
            ['worker', status.worker.pending_jobs > 0 ? `${status.worker.pending_jobs} queued` : 'idle'],
          ] as [string, string][]).map(([key, val]) => {
            const color = statusColor(val)
            return (
              <span key={key} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: color,
                    display: 'inline-block',
                    flexShrink: 0,
                  }}
                />
                <span style={{ color: '#374151', textTransform: 'capitalize' }}>{key}</span>
                <span style={{ color, fontWeight: 500 }}>{val}</span>
              </span>
            )
          })}
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <KpiCard label="Total scans" value={scans.length} />
        <KpiCard label="Active" value={activeScans} accent={activeScans > 0 ? '#1D4ED8' : undefined} />
        <KpiCard label="Completed" value={doneScans} accent="#067647" />
        <KpiCard label="Total findings" value={totalFindings} />
      </div>

      {/* Recent scans */}
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#111827' }}>Recent scans</span>
        <Link href="/scans" style={{ fontSize: 13, color: '#6B7280', textDecoration: 'none' }}>
          View all
        </Link>
      </div>

      <div className="panel" style={{ overflow: 'hidden' }}>
        {recentScans.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            No scans yet. Click "New scan" to start.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Scan ID</th>
                <th>Repository</th>
                <th>State</th>
                <th>Findings</th>
                <th>Started</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {recentScans.map((scan) => (
                <tr key={scan.id}>
                  <td>
                    <Link
                      href={`/scans/${scan.id}`}
                      style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#1D4ED8', textDecoration: 'none' }}
                    >
                      {scan.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td style={{ maxWidth: 240 }}>
                    <span style={{ fontSize: 13, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                      {scan.repo_locator}
                    </span>
                  </td>
                  <td><StateBadge state={scan.state} size="sm" /></td>
                  <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                    {scan.n_findings}
                  </td>
                  <td style={{ fontSize: 12, color: '#9CA3AF', whiteSpace: 'nowrap' }}>
                    {formatDate(scan.started_at)}
                  </td>
                  <td style={{ fontSize: 12, color: '#9CA3AF', fontFamily: 'JetBrains Mono, monospace' }}>
                    {formatDuration(scan.started_at, scan.finished_at)}
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
