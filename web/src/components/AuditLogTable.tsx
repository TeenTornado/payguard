'use client'

import { useState, useEffect } from 'react'
import { getAuditLog, verifyAuditChain } from '@/lib/api'
import type { AuditEvent } from '@/lib/types'
import { formatDate, truncateHash } from '@/lib/format'

export function AuditLogTable() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [chainOk, setChainOk] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; error: string | null; n_events: number } | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const data = await getAuditLog(50)
        setEvents(data.events)
        setTotal(data.total)
        setChainOk(data.chain_ok)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load audit log')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const handleVerify = async () => {
    setVerifyLoading(true)
    setVerifyResult(null)
    try {
      const result = await verifyAuditChain()
      setVerifyResult(result)
    } catch (e: unknown) {
      setVerifyResult({ ok: false, error: e instanceof Error ? e.message : 'Verify failed', n_events: 0 })
    } finally {
      setVerifyLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="panel" style={{ padding: 16 }}>
        {[...Array(8)].map((_, i) => (
          <div key={i} style={{ height: 32, background: '#F3F4F6', borderRadius: 4, marginBottom: 4, opacity: 1 - i * 0.1 }} />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="panel" style={{ padding: 16, color: '#B42318', fontSize: 13 }}>
        Error: {error}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Chain status + verify button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {chainOk != null && (
          <span style={{ fontSize: 12, color: chainOk ? '#067647' : '#B42318', fontWeight: 500 }}>
            {chainOk ? 'Chain integrity: OK' : 'Chain integrity: BROKEN'}
          </span>
        )}
        <button
          onClick={handleVerify}
          disabled={verifyLoading}
          style={{
            padding: '5px 12px',
            background: '#fff',
            border: '1px solid #E5E7EB',
            borderRadius: 6,
            fontSize: 12,
            color: '#374151',
            cursor: verifyLoading ? 'not-allowed' : 'pointer',
            fontWeight: 500,
          }}
        >
          {verifyLoading ? 'Verifying...' : 'Verify chain'}
        </button>
        <span style={{ fontSize: 12, color: '#9CA3AF' }}>{total} events</span>
      </div>

      {/* Verify result */}
      {verifyResult && (
        <div
          style={{
            padding: '8px 14px',
            background: verifyResult.ok ? '#ECFDF3' : '#FEF3F2',
            border: `1px solid ${verifyResult.ok ? '#BBF7D0' : '#FECACA'}`,
            borderRadius: 6,
            fontSize: 13,
            color: verifyResult.ok ? '#166534' : '#B42318',
          }}
        >
          {verifyResult.ok
            ? `Chain OK — ${verifyResult.n_events} events verified`
            : `Chain BROKEN — ${verifyResult.error ?? 'Unknown error'}`}
        </div>
      )}

      <div className="panel" style={{ overflow: 'hidden' }}>
        {events.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            No audit events recorded yet.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>Seq</th>
                <th>Timestamp</th>
                <th>Actor</th>
                <th>Event</th>
                <th>Object</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.seq}>
                  <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#9CA3AF' }}>
                    {ev.seq}
                  </td>
                  <td style={{ color: '#9CA3AF', fontSize: 12, whiteSpace: 'nowrap' }}>
                    {formatDate(ev.timestamp)}
                  </td>
                  <td style={{ fontSize: 12, color: '#374151' }}>{ev.actor}</td>
                  <td style={{ fontSize: 12, fontWeight: 500, color: '#111827' }}>{ev.event}</td>
                  <td style={{ fontSize: 12, color: '#6B7280' }}>
                    {ev.object_type} / <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>{ev.object_id?.slice(0, 8)}</span>
                  </td>
                  <td>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#9CA3AF' }}>
                      {truncateHash(ev.hash)}
                    </span>
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
