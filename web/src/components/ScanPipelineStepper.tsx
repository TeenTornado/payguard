'use client'

import { useEffect, useState } from 'react'
import type { ScanState } from '@/lib/types'
import { scanEvents } from '@/lib/api'

const STEPS: ScanState[] = [
  'INGEST',
  'DISCOVER',
  'STATIC',
  'SEMANTIC',
  'NORMALIZE',
  'SCORE',
  'SELECT_SCENARIOS',
  'VERIFY',
  'DECIDE',
  'HUMAN_GATE',
  'REMEDIATE',
  'DONE',
]

const TERMINAL: ScanState[] = ['DONE', 'FAILED']

interface Props {
  scanId: string
  initialState: ScanState
  onStateChange?: (state: ScanState) => void
}

export function ScanPipelineStepper({ scanId, initialState, onStateChange }: Props) {
  const [currentState, setCurrentState] = useState<ScanState>(initialState)
  const [lastMessage, setLastMessage] = useState<string>('')

  useEffect(() => {
    if (TERMINAL.includes(initialState)) {
      setCurrentState(initialState)
      return
    }

    const es = scanEvents(scanId)

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.state) {
          setCurrentState(data.state as ScanState)
          onStateChange?.(data.state as ScanState)
        }
        if (data.message) {
          setLastMessage(data.message)
        }
        if (TERMINAL.includes(data.state)) {
          es.close()
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      es.close()
    }

    return () => {
      es.close()
    }
  }, [scanId, initialState, onStateChange])

  const currentIdx = STEPS.indexOf(currentState)
  const isFailed = currentState === 'FAILED'

  return (
    <div style={{ padding: '20px 0' }}>
      {/* Step dots */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto', paddingBottom: 8 }}>
        {STEPS.map((step, idx) => {
          const isDone = !isFailed && (currentIdx > idx || currentState === 'DONE')
          const isActive = !isFailed && currentIdx === idx && !TERMINAL.includes(currentState)
          const isCurrent = step === currentState
          const isPending = currentIdx < idx && !isFailed

          let dotColor = '#D1D5DB'
          let dotBorder = '#D1D5DB'
          let labelColor = '#9CA3AF'

          if (isFailed && isCurrent) {
            dotColor = '#FEF3F2'
            dotBorder = '#B42318'
            labelColor = '#B42318'
          } else if (isDone) {
            dotColor = '#111827'
            dotBorder = '#111827'
            labelColor = '#374151'
          } else if (isActive) {
            dotColor = '#fff'
            dotBorder = '#111827'
            labelColor = '#111827'
          }

          return (
            <div key={step} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
              {/* Connector line */}
              {idx > 0 && (
                <div
                  style={{
                    width: 24,
                    height: 1,
                    background: isDone ? '#111827' : '#E5E7EB',
                    flexShrink: 0,
                  }}
                />
              )}

              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                {/* Dot */}
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: dotColor,
                    border: `2px solid ${dotBorder}`,
                    flexShrink: 0,
                    ...(isActive ? { animation: 'spin 1.2s linear infinite' } : {}),
                  }}
                />
                {/* Label */}
                <span
                  style={{
                    fontSize: 10,
                    color: labelColor,
                    fontWeight: isCurrent ? 600 : 400,
                    whiteSpace: 'nowrap',
                    letterSpacing: '0.02em',
                    textTransform: 'uppercase',
                  }}
                >
                  {step.replace(/_/g, ' ')}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Status message */}
      {lastMessage && !TERMINAL.includes(currentState) && (
        <div style={{ fontSize: 12, color: '#6B7280', marginTop: 8, paddingLeft: 2 }}>
          {lastMessage}
        </div>
      )}

      {isFailed && (
        <div
          style={{
            marginTop: 12,
            padding: '8px 14px',
            background: '#FEF3F2',
            border: '1px solid #FECACA',
            borderRadius: 6,
            fontSize: 13,
            color: '#B42318',
          }}
        >
          Scan failed. {lastMessage}
        </div>
      )}
    </div>
  )
}
