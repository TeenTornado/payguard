'use client'

import { useEffect, useState } from 'react'
import { getLatestEval } from '@/lib/api'
import { formatPct, formatDate } from '@/lib/format'
import type { EvalReport } from '@/lib/types'

export default function EvaluationPage() {
  const [report, setReport] = useState<EvalReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getLatestEval()
      .then((r) => { setReport(r); setLoading(false) })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load eval')
        setLoading(false)
      })
  }, [])

  const f1Color = (f1: number) =>
    f1 >= 0.85 ? '#067647' : f1 >= 0.6 ? '#B54708' : '#B42318'

  if (loading) {
    return (
      <div>
        <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Evaluation</div>
        <div style={{ display: 'flex', gap: 12 }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{ width: 160, height: 80, background: '#F3F4F6', borderRadius: 6 }} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Evaluation</div>

      {error && (
        <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#B42318' }}>
          {error}
        </div>
      )}

      {!report && !error ? (
        <div className="panel" style={{ padding: '40px 32px' }}>
          <div style={{ maxWidth: 480 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
              No test-split evaluation report
            </div>
            <div style={{ fontSize: 13, color: '#6B7280', marginBottom: 20, lineHeight: 1.6 }}>
              The test split is frozen and has not been evaluated yet. The evaluation command runs precision/recall metrics against a held-out labeled dataset.
            </div>
            <div
              style={{
                background: '#0F172A',
                color: '#E2E8F0',
                padding: '12px 16px',
                borderRadius: 6,
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: 13,
                display: 'inline-block',
                marginBottom: 16,
              }}
            >
              make eval
            </div>
            <div style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6 }}>
              Results will appear here after the first test-split eval run.
              <br />
              Do not run on the test split during development — use{' '}
              <span style={{ fontFamily: 'JetBrains Mono, monospace' }}>make eval-dev-all</span>{' '}
              for the validation split.
            </div>
          </div>
        </div>
      ) : report ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Overall metrics */}
          <div className="panel" style={{ padding: '20px 24px' }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 16 }}>
              Overall metrics
            </div>
            <div style={{ display: 'flex', gap: 40, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>F1</div>
                <div style={{ fontSize: 32, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: f1Color(report.overall_f1) }}>
                  {formatPct(report.overall_f1)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Precision</div>
                <div style={{ fontSize: 32, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#111827' }}>
                  {formatPct(report.overall_precision)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: '#6B7280', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Recall</div>
                <div style={{ fontSize: 32, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#111827' }}>
                  {formatPct(report.overall_recall)}
                </div>
              </div>
            </div>
            {report.run_at && (
              <div style={{ fontSize: 12, color: '#9CA3AF', marginTop: 16 }}>
                Evaluated: {formatDate(report.run_at)}
              </div>
            )}
          </div>

          {/* Per-class metrics */}
          {report.per_class && report.per_class.length > 0 && (
            <div className="panel" style={{ overflow: 'hidden' }}>
              <div style={{ padding: '14px 20px', fontWeight: 600, fontSize: 14, color: '#111827', borderBottom: '1px solid #E5E7EB' }}>
                Per-class metrics
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Defect class</th>
                    <th>F1</th>
                    <th>Precision</th>
                    <th>Recall</th>
                    <th>TP</th>
                    <th>FP</th>
                    <th>FN</th>
                  </tr>
                </thead>
                <tbody>
                  {report.per_class.map((c) => (
                    <tr key={c.defect_class}>
                      <td style={{ fontWeight: 500, fontSize: 13 }}>
                        {c.defect_class.replace(/_/g, ' ')}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 13, color: f1Color(c.f1), fontWeight: 600 }}>
                        {formatPct(c.f1)}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                        {formatPct(c.precision)}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                        {formatPct(c.recall)}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                        {c.n_true_positive}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                        {c.n_false_positive}
                      </td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#374151' }}>
                        {c.n_false_negative}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
