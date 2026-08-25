'use client'

import { useEffect, useState } from 'react'
import { FindingsTable } from '@/components/FindingsTable'
import { listScans } from '@/lib/api'
import type { ScanListItem } from '@/lib/types'

export default function FindingsPage() {
  const [scans, setScans] = useState<ScanListItem[]>([])
  // undefined = not chosen yet; '' = all scans; otherwise a scan id
  const [scanId, setScanId] = useState<string | undefined>(undefined)

  useEffect(() => {
    listScans()
      .then((s) => {
        setScans(s)
        // Default to the most recent scan so the page isn't a wall of duplicates.
        setScanId(s.length > 0 ? s[0].id : '')
      })
      .catch(() => setScanId(''))
  }, [])

  const label = (s: ScanListItem) => {
    const repo = (s.repo_locator ?? '').split('/').filter(Boolean).slice(-1)[0] || s.id.slice(0, 8)
    return `${repo} · ${s.n_findings ?? 0} findings · ${s.state}`
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 600, color: '#111827' }}>Findings</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#6B7280' }}>Scan</span>
          <select
            value={scanId ?? ''}
            onChange={(e) => setScanId(e.target.value)}
            style={{
              padding: '5px 8px',
              border: '1px solid #E5E7EB',
              borderRadius: 6,
              fontSize: 12,
              color: '#374151',
              background: '#fff',
              cursor: 'pointer',
              maxWidth: 320,
            }}
          >
            <option value="">All scans</option>
            {scans.map((s) => (
              <option key={s.id} value={s.id}>
                {label(s)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Wait until we've picked a default scan to avoid a flash of all-scans. */}
      {scanId !== undefined && (
        <FindingsTable scanId={scanId || undefined} showFilters={true} />
      )}
    </div>
  )
}
