'use client'

import { useEffect, useState } from 'react'
import { getSettings, updateSettings } from '@/lib/api'
import type { Settings } from '@/lib/types'

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  useEffect(() => {
    getSettings()
      .then((s) => { setSettings(s); setLoading(false) })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load settings')
        setLoading(false)
      })
  }, [])

  const handleUpdate = async (patch: Partial<Settings>) => {
    if (!settings) return
    setSaving(true)
    setSavedMsg(null)
    setError(null)
    try {
      const updated = await updateSettings(patch)
      setSettings(updated)
      setSavedMsg('Saved')
      setTimeout(() => setSavedMsg(null), 2000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 12,
    color: '#6B7280',
    fontWeight: 500,
    marginBottom: 6,
    display: 'block',
  }

  if (loading) {
    return (
      <div>
        <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Settings</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{ height: 80, background: '#F3F4F6', borderRadius: 6 }} />
          ))}
        </div>
      </div>
    )
  }

  if (!settings) {
    return (
      <div>
        <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Settings</div>
        {error && (
          <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, fontSize: 13, color: '#B42318' }}>
            {error}
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Settings</div>

      {error && (
        <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#B42318' }}>
          {error}
        </div>
      )}

      {savedMsg && (
        <div style={{ padding: '8px 12px', background: '#ECFDF3', border: '1px solid #BBF7D0', borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#067647' }}>
          {savedMsg}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Environment (read-only) */}
        <div className="panel" style={{ padding: '16px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 14 }}>Environment</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <span style={labelStyle}>Gateway mode</span>
              <span style={{ fontSize: 13, fontWeight: 500, color: '#111827', fontFamily: 'JetBrains Mono, monospace' }}>
                {settings.gateway_mode}
              </span>
            </div>
          </div>
          <div
            style={{
              marginTop: 14,
              padding: '8px 12px',
              background: '#ECFDF3',
              border: '1px solid #BBF7D0',
              borderRadius: 5,
            }}
          >
            <span style={{ fontSize: 12, color: '#067647', fontWeight: 600 }}>TEST MODE ONLY</span>
            <span style={{ fontSize: 12, color: '#374151', marginLeft: 8 }}>
              API keys not prefixed with{' '}
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>rzp_test_</span>{' '}
              are rejected.
            </span>
          </div>
        </div>

        {/* Detection thresholds */}
        <div className="panel" style={{ padding: '16px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 16 }}>Detection thresholds</div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ ...labelStyle, display: 'flex', justifyContent: 'space-between' }}>
              <span>Advisory threshold</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#111827', fontWeight: 600 }}>
                {settings.advisory_threshold.toFixed(2)}
              </span>
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.advisory_threshold}
              onChange={(e) => setSettings({ ...settings, advisory_threshold: parseFloat(e.target.value) })}
              onMouseUp={(e) => handleUpdate({ advisory_threshold: parseFloat((e.target as HTMLInputElement).value) })}
              style={{ width: '100%', margin: '4px 0' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#9CA3AF' }}>
              <span>0.0</span><span>0.5</span><span>1.0</span>
            </div>
            <div style={{ fontSize: 12, color: '#6B7280', marginTop: 6 }}>
              Findings with confidence at or above this threshold enter ADVISORY state.
            </div>
          </div>

          <div>
            <label style={{ ...labelStyle, display: 'flex', justifyContent: 'space-between' }}>
              <span>Verify threshold</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#111827', fontWeight: 600 }}>
                {settings.verify_threshold.toFixed(2)}
              </span>
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.verify_threshold}
              onChange={(e) => setSettings({ ...settings, verify_threshold: parseFloat(e.target.value) })}
              onMouseUp={(e) => handleUpdate({ verify_threshold: parseFloat((e.target as HTMLInputElement).value) })}
              style={{ width: '100%', margin: '4px 0' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#9CA3AF' }}>
              <span>0.0</span><span>0.5</span><span>1.0</span>
            </div>
            <div style={{ fontSize: 12, color: '#6B7280', marginTop: 6 }}>
              Findings with confidence at or above this threshold are auto-queued for verification.
            </div>
          </div>
        </div>

        {/* Chaos mode — two independent fault switches (shared cross-process sentinel) */}
        <div className="panel" style={{ padding: '16px 20px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 6 }}>Chaos mode</div>
          <div style={{ fontSize: 12, color: '#6B7280', lineHeight: 1.5, marginBottom: 14 }}>
            Fault injection for demoing the degraded paths. Each switch is independent and is
            read by the worker and gateway processes, not just this API.
          </div>

          <ChaosToggle
            title="LLM degradation"
            desc="The worker skips LLM analysis; new scans run static-only and report llm_status = FAILED."
            on={settings.chaos_llm}
            disabled={saving}
            onToggle={() => handleUpdate({ chaos_llm: !settings.chaos_llm })}
          />

          <div style={{ height: 1, background: '#F3F4F6', margin: '14px 0' }} />

          <ChaosToggle
            title="Gateway failure"
            desc="The gateway returns 503 on payment/verification calls. Verifications ERROR after bounded retries — never VERIFIED, no MEASURED amount."
            on={settings.chaos_gateway}
            disabled={saving}
            onToggle={() => handleUpdate({ chaos_gateway: !settings.chaos_gateway })}
          />

          {(settings.chaos_llm || settings.chaos_gateway) && (
            <div
              style={{
                marginTop: 14,
                padding: '8px 12px',
                background: '#FEF3F2',
                border: '1px solid #FECACA',
                borderRadius: 5,
              }}
            >
              <span style={{ fontSize: 12, color: '#B42318', fontWeight: 600 }}>Chaos ON</span>
              <span style={{ fontSize: 12, color: '#374151', marginLeft: 8 }}>
                {settings.chaos_llm && 'LLM degraded. '}
                {settings.chaos_gateway && 'Gateway failing verification calls.'}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ChaosToggle({
  title,
  desc,
  on,
  disabled,
  onToggle,
}: {
  title: string
  desc: string
  on: boolean
  disabled: boolean
  onToggle: () => void
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: '#374151', marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, color: '#6B7280', lineHeight: 1.5 }}>{desc}</div>
      </div>
      <button
        onClick={onToggle}
        disabled={disabled}
        aria-label={`Toggle ${title}`}
        aria-pressed={on}
        style={{
          width: 44,
          height: 24,
          borderRadius: 12,
          border: 'none',
          background: on ? '#B42318' : '#D1D5DB',
          cursor: disabled ? 'not-allowed' : 'pointer',
          position: 'relative',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 3,
            left: on ? 23 : 3,
            width: 18,
            height: 18,
            borderRadius: '50%',
            background: '#fff',
            boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
          }}
        />
      </button>
    </div>
  )
}
