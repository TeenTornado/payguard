'use client'

import { useEffect, useState } from 'react'
import { getEvalCompare } from '@/lib/api'
import type { EvalCompare } from '@/lib/types'

const pct = (x?: number | null) => (x == null ? '—' : `${(x * 100).toFixed(1)}%`)

function RunnablePanel({ cmp }: { cmp: EvalCompare }) {
  const rav = cmp.runnable_avd
  if (!rav) return null
  const color = (s: string) => (s === 'D' ? '#067647' : '#374151')
  return (
    <div className="panel" style={{ padding: '18px 22px', marginBottom: 20 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 4 }}>
        The verifier restores precision — A / C / D on runnable targets (n={rav.n})
      </div>
      <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 14 }}>
        D counts a class only if it reaches VERIFIED in the sandbox. The LLM widens the net (C
        precision &lt; A); the verifier removes the false positives it can’t reproduce (D).
      </div>
      <table>
        <thead>
          <tr><th>System</th><th>Macro P</th><th>Macro R</th><th>Macro F1</th><th>Total FP</th></tr>
        </thead>
        <tbody>
          {['A', 'C', 'D'].filter((s) => rav.systems[s]).map((s) => {
            const m = rav.systems[s].macro
            return (
              <tr key={s}>
                <td style={{ fontWeight: 600, color: color(s) }}>{s}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace', color: color(s) }}>{pct(m.p)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{pct(m.r)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace', color: color(s) }}>{pct(m.f1)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace', color: color(s) }}>{rav.systems[s].total_fp}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ComparePanel({ cmp }: { cmp: EvalCompare }) {
  const d = cmp.c_vs_crag
  const systems = ['A', 'B', 'C', 'C+RAG'].filter((s) => cmp.summaries[s])
  const model = cmp.summaries[systems[0]]?.provider_model
  return (
    <div className="panel" style={{ padding: '18px 22px', marginBottom: 20 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: '#111827', marginBottom: 4 }}>
        Frozen test split — systems compared
        {model && <span style={{ fontWeight: 400, fontSize: 12, color: '#9CA3AF' }}> · analyzer {model}</span>}
      </div>
      <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 14 }}>
        A = static · B = LLM only · C = static ∪ LLM · C+RAG = static ∪ grounded LLM. Same frozen split.
      </div>
      <table>
        <thead>
          <tr><th>System</th><th>Macro P</th><th>Macro R</th><th>Macro F1</th><th>Total FP</th></tr>
        </thead>
        <tbody>
          {systems.map((s) => {
            const m = cmp.summaries[s]
            return (
              <tr key={s}>
                <td style={{ fontWeight: 600 }}>{s}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{pct(m.macro.p)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{pct(m.macro.r)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{pct(m.macro.f1)}</td>
                <td style={{ fontFamily: 'JetBrains Mono, monospace' }}>{m.total_fp}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {d && (
        <div style={{ marginTop: 14, padding: '12px 14px', background: '#F9FAFB', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 13, color: '#374151' }}>
          <strong>C → C+RAG</strong> (grounding, measured):{' '}
          FP {d.fp_before} → {d.fp_after} · precision {pct(d.precision_before)} → {pct(d.precision_after)} ·
          recall {pct(d.recall_before)} → {pct(d.recall_after)}
          {d.fp_after === d.fp_before && d.precision_after === d.precision_before && (
            <span style={{ color: '#6B7280' }}> — no change; grounding did not beat baseline, kept behind a flag (see docs/evaluation.md).</span>
          )}
        </div>
      )}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="panel" style={{ padding: '40px 32px' }}>
      <div style={{ maxWidth: 520 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
          No evaluation reports yet
        </div>
        <div style={{ fontSize: 13, color: '#6B7280', marginBottom: 20, lineHeight: 1.6 }}>
          Run the frozen test-split evaluation (A/B/C/C+RAG) and the runnable-target A/C/D
          (verifier) evaluation. Neither is tuned on the test split.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {['make eval', 'python -m payguard.eval.verify_eval'].map((cmd) => (
            <div key={cmd} style={{ background: '#0F172A', color: '#E2E8F0', padding: '10px 14px', borderRadius: 6, fontFamily: 'JetBrains Mono, monospace', fontSize: 13, display: 'inline-block' }}>
              {cmd}
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, marginTop: 16 }}>
          Results appear here after the runs. The full verdict is in docs/evaluation.md.
        </div>
      </div>
    </div>
  )
}

export default function EvaluationPage() {
  const [cmp, setCmp] = useState<EvalCompare | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getEvalCompare()
      .then((c) => { setCmp(c); setLoading(false) })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load evaluation')
        setLoading(false)
      })
  }, [])

  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>Evaluation</div>

      {error && (
        <div style={{ padding: '10px 14px', background: '#FEF3F2', border: '1px solid #FECACA', borderRadius: 6, marginBottom: 16, fontSize: 13, color: '#B42318' }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {[...Array(2)].map((_, i) => (
            <div key={i} style={{ height: 180, background: '#F3F4F6', borderRadius: 8 }} />
          ))}
        </div>
      ) : cmp && Object.keys(cmp.summaries).length > 0 ? (
        <>
          <RunnablePanel cmp={cmp} />
          <ComparePanel cmp={cmp} />
        </>
      ) : (
        !error && <EmptyState />
      )}
    </div>
  )
}
