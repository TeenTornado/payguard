'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { createScan, preflightScan } from '@/lib/api'
import type { PreflightResult } from '@/lib/types'

export default function NewScanPage() {
  const router = useRouter()
  const [repoPath, setRepoPath] = useState('')
  const [preflight, setPreflight] = useState<PreflightResult | null>(null)
  const [preflightError, setPreflightError] = useState<string | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)
  const [scanLoading, setScanLoading] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)

  const handlePreflight = async () => {
    if (!repoPath.trim()) return
    setPreflightLoading(true)
    setPreflightError(null)
    setPreflight(null)
    try {
      const result = await preflightScan(repoPath.trim())
      setPreflight(result)
    } catch (e: unknown) {
      setPreflightError(e instanceof Error ? e.message : 'Preflight failed')
    } finally {
      setPreflightLoading(false)
    }
  }

  const handleStartScan = async () => {
    if (!repoPath.trim()) return
    setScanLoading(true)
    setScanError(null)
    try {
      const scan = await createScan(repoPath.trim())
      router.push(`/scans/${scan.id}`)
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : 'Failed to start scan')
      setScanLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 480 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20, fontSize: 13 }}>
        <Link href="/scans" style={{ color: '#6B7280', textDecoration: 'none' }}>Scans</Link>
        <span style={{ color: '#D1D5DB' }}>/</span>
        <span style={{ color: '#111827' }}>New scan</span>
      </div>

      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>New scan</div>

      <div className="panel" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Repo path */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 500, color: '#374151' }}>Repository path</label>
          <input
            type="text"
            value={repoPath}
            onChange={(e) => {
              setRepoPath(e.target.value)
              setPreflight(null)
              setPreflightError(null)
            }}
            onKeyDown={(e) => e.key === 'Enter' && handlePreflight()}
            placeholder="/path/to/repo"
            style={{
              padding: '8px 12px',
              border: '1px solid #E5E7EB',
              borderRadius: 6,
              fontSize: 13,
              fontFamily: 'JetBrains Mono, monospace',
              color: '#111827',
              outline: 'none',
            }}
          />
        </div>

        {/* Preflight */}
        <button
          onClick={handlePreflight}
          disabled={!repoPath.trim() || preflightLoading}
          style={{
            alignSelf: 'flex-start',
            padding: '7px 14px',
            background: '#F6F7F9',
            border: '1px solid #E5E7EB',
            borderRadius: 6,
            fontSize: 13,
            color: '#374151',
            cursor: repoPath.trim() && !preflightLoading ? 'pointer' : 'not-allowed',
            fontWeight: 500,
          }}
        >
          {preflightLoading ? 'Checking...' : 'Preflight check'}
        </button>

        {preflightError && (
          <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, fontSize: 13, color: '#B42318' }}>
            {preflightError}
          </div>
        )}

        {preflight && (
          <div style={{ padding: '12px 16px', background: '#ECFDF3', border: '1px solid #BBF7D0', borderRadius: 6, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#166534' }}>
              <span>Files found</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>{preflight.file_count}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#166534' }}>
              <span>Manifest present</span>
              <span style={{ fontWeight: 600 }}>{preflight.manifest_present ? 'Yes' : 'No'}</span>
            </div>
          </div>
        )}

        {scanError && (
          <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, fontSize: 13, color: '#B42318' }}>
            {scanError}
          </div>
        )}

        {/* Start scan */}
        <button
          onClick={handleStartScan}
          disabled={!repoPath.trim() || scanLoading}
          style={{
            padding: '10px 16px',
            background: repoPath.trim() && !scanLoading ? '#111827' : '#D1D5DB',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 500,
            cursor: repoPath.trim() && !scanLoading ? 'pointer' : 'not-allowed',
          }}
        >
          {scanLoading ? 'Starting...' : 'Start scan'}
        </button>
      </div>
    </div>
  )
}
