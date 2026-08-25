'use client'

import { useEffect, useState, useRef } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { getScan } from '@/lib/api'
import { ScanPipelineStepper } from '@/components/ScanPipelineStepper'
import { FindingsTable } from '@/components/FindingsTable'
import { KpiCard } from '@/components/KpiCard'
import { formatDate, formatDuration } from '@/lib/format'
import type { Scan, ScanState } from '@/lib/types'

const TERMINAL: ScanState[] = ['DONE', 'FAILED']

export default function ScanDetailPage() {
  const params = useParams()
  const scanId = params.id as string
  const [scan, setScan] = useState<Scan | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!scanId) return

    const load = async () => {
      try {
        const s = await getScan(scanId)
        setScan(s)
        if (TERMINAL.includes(s.state) && intervalRef.current) {
          clearInterval(intervalRef.current)
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load scan')
      }
    }

    load()
    intervalRef.current = setInterval(load, 3000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [scanId])

  const handleStateChange = (state: ScanState) => {
    if (TERMINAL.includes(state) && intervalRef.current) {
      clearInterval(intervalRef.current)
      // Final refresh to get full data
      getScan(scanId).then(setScan).catch(() => {})
    }
  }

  if (error) {
    return (
      <div>
        <Link href="/scans" style={{ color: '#6B7280', fontSize: 13, textDecoration: 'none' }}>
          Back to scans
        </Link>
        <div className="panel" style={{ marginTop: 16, padding: '14px 16px', color: '#B42318', fontSize: 13 }}>
          Error: {error}
        </div>
      </div>
    )
  }

  if (!scan) {
    return (
      <div>
        <Link href="/scans" style={{ color: '#6B7280', fontSize: 13, textDecoration: 'none' }}>
          Back to scans
        </Link>
        <div style={{ marginTop: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} style={{ width: 160, height: 80, background: '#F3F4F6', borderRadius: 6 }} />
          ))}
        </div>
      </div>
    )
  }

  const isDone = TERMINAL.includes(scan.state)

  return (
    <div>
      {/* Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 13 }}>
        <Link href="/scans" style={{ color: '#6B7280', textDecoration: 'none' }}>Scans</Link>
        <span style={{ color: '#D1D5DB' }}>/</span>
        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#374151' }}>
          {scanId.slice(0, 8)}
        </span>
        <span style={{ color: '#D1D5DB' }}>·</span>
        <span style={{ color: '#9CA3AF', fontSize: 12, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {scan.repo_locator}
        </span>
      </div>

      {/* LLM status banners */}
      {scan.llm_status === 'FAILED' && (
        <div style={{ background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, padding: '8px 14px', marginBottom: 16, color: '#B42318', fontSize: 13 }}>
          LLM analysis failed — only static rules applied. Some defects may be missed.
        </div>
      )}
      {scan.llm_status === 'DEGRADED' && (
        <div style={{ background: '#FFFAEB', border: '1px solid #FEF3C7', borderRadius: 6, padding: '8px 14px', marginBottom: 16, color: '#B54708', fontSize: 13 }}>
          LLM analysis degraded — partial AI results only.
        </div>
      )}

      {/* Pipeline stepper */}
      <div className="panel" style={{ marginBottom: 20, padding: '16px 20px' }}>
        <ScanPipelineStepper
          scanId={scanId}
          initialState={scan.state}
          onStateChange={handleStateChange}
        />
      </div>

      {/* KPI cards */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <KpiCard label="Findings" value={scan.n_findings ?? 0} />
        <KpiCard label="Advisory" value={scan.n_advisory ?? 0} accent="#344054" />
        <KpiCard label="Verified" value={scan.n_verified ?? 0} accent="#067647" />
        <KpiCard label="Exceptions" value={scan.n_exception ?? 0} accent="#B54708" />
        <KpiCard
          label="Duration"
          value={formatDuration(scan.started_at, scan.finished_at)}
          sub={scan.finished_at ? `Finished ${formatDate(scan.finished_at)}` : 'In progress'}
        />
      </div>

      {/* Findings table (always show, even while running) */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#111827', marginBottom: 12 }}>
          Findings
        </div>
        <FindingsTable scanId={scanId} showFilters={true} />
      </div>
    </div>
  )
}
