'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createScan, preflightScan } from '@/lib/api'
import type { PreflightResult } from '@/lib/types'

interface Props {
  open: boolean
  onClose: () => void
}

export function NewScanDrawer({ open, onClose }: Props) {
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
      onClose()
      setRepoPath('')
      setPreflight(null)
      router.push(`/scans/${scan.id}`)
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : 'Failed to start scan')
    } finally {
      setScanLoading(false)
    }
  }

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.3)',
          zIndex: 200,
        }}
      />

      {/* Drawer */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: 400,
          background: '#fff',
          borderLeft: '1px solid #E5E7EB',
          zIndex: 201,
          display: 'flex',
          flexDirection: 'column',
          padding: 24,
          gap: 20,
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: '#111827' }}>New scan</span>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: 20,
              color: '#9CA3AF',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '2px 6px',
            }}
          >
            x
          </button>
        </div>

        {/* Repo path input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 500, color: '#374151' }}>
            Repository path
          </label>
          <input
            type="text"
            value={repoPath}
            onChange={(e) => {
              setRepoPath(e.target.value)
              setPreflight(null)
              setPreflightError(null)
            }}
            placeholder="/path/to/repo"
            onKeyDown={(e) => e.key === 'Enter' && handlePreflight()}
            style={{
              padding: '8px 12px',
              border: '1px solid #E5E7EB',
              borderRadius: 6,
              fontSize: 13,
              fontFamily: 'JetBrains Mono, monospace',
              outline: 'none',
              color: '#111827',
            }}
          />
        </div>

        {/* Preflight button */}
        <button
          onClick={handlePreflight}
          disabled={!repoPath.trim() || preflightLoading}
          style={{
            padding: '8px 16px',
            background: preflightLoading ? '#F3F4F6' : '#F6F7F9',
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

        {/* Preflight result */}
        {preflightError && (
          <div
            style={{
              padding: '10px 14px',
              background: '#FEF3F2',
              border: '1px solid #FECACA',
              borderRadius: 6,
              fontSize: 13,
              color: '#B42318',
            }}
          >
            {preflightError}
          </div>
        )}

        {preflight && (
          <div
            style={{
              padding: '12px 14px',
              background: '#F0FDF4',
              border: '1px solid #BBF7D0',
              borderRadius: 6,
              fontSize: 13,
              color: '#166534',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Files found</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
                {preflight.file_count}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Manifest present</span>
              <span style={{ fontWeight: 600 }}>
                {preflight.manifest_present ? 'Yes' : 'No'}
              </span>
            </div>
          </div>
        )}

        {scanError && (
          <div
            style={{
              padding: '10px 14px',
              background: '#FEF3F2',
              border: '1px solid #FECACA',
              borderRadius: 6,
              fontSize: 13,
              color: '#B42318',
            }}
          >
            {scanError}
          </div>
        )}

        <div style={{ flex: 1 }} />

        {/* Start scan button */}
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
    </>
  )
}
