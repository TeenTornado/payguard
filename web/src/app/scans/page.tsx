'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { listScans } from '@/lib/api'
import { StateBadge } from '@/components/StateBadge'
import { formatDate, formatDuration } from '@/lib/format'
import type { ScanListItem } from '@/lib/types'

export default function ScansPage() {
  const [scans, setScans] = useState<ScanListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await listScans()
      setScans(s)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load scans')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <span style={{ fontSize: 20, fontWeight: 600, color: '#111827' }}>Scans</span>
        <span style={{ fontSize: 12, color: '#9CA3AF' }}>{scans.length} total</span>
      </div>

      <div className="panel" style={{ overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 16 }}>
            {[...Array(6)].map((_, i) => (
              <div key={i} style={{ height: 32, background: '#F3F4F6', borderRadius: 4, marginBottom: 4, opacity: 1 - i * 0.12 }} />
            ))}
          </div>
        ) : error ? (
          <div style={{ padding: '14px 16px', color: '#B42318', fontSize: 13 }}>Error: {error}</div>
        ) : scans.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            No scans yet. Click <strong>New scan</strong> to get started.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Repository</th>
                <th>State</th>
                <th>Findings</th>
                <th>LLM</th>
                <th>Static</th>
                <th>Duration</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {scans.map((s) => (
                <tr key={s.id}>
                  <td>
                    <Link
                      href={`/scans/${s.id}`}
                      style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#1D4ED8', textDecoration: 'none' }}
                    >
                      {s.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td style={{ maxWidth: 240 }}>
                    <Link
                      href={`/scans/${s.id}`}
                      style={{ fontSize: 13, color: '#111827', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}
                    >
                      {s.repo_locator}
                    </Link>
                  </td>
                  <td><StateBadge state={s.state} size="sm" /></td>
                  <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>{s.n_findings}</td>
                  <td>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 500,
                      color: !s.llm_status || s.llm_status === 'OK' ? '#067647' : s.llm_status === 'DEGRADED' ? '#B54708' : '#B42318',
                    }}>
                      {s.llm_status ?? 'OK'}
                    </span>
                  </td>
                  <td>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 500,
                      color: !s.static_status || s.static_status === 'OK' ? '#067647' : s.static_status === 'DEGRADED' ? '#B54708' : '#B42318',
                    }}>
                      {s.static_status ?? 'OK'}
                    </span>
                  </td>
                  <td style={{ fontSize: 12, color: '#9CA3AF', fontFamily: 'JetBrains Mono, monospace' }}>
                    {formatDuration(s.started_at, s.finished_at)}
                  </td>
                  <td style={{ fontSize: 12, color: '#9CA3AF', whiteSpace: 'nowrap' }}>
                    {formatDate(s.started_at)}
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
