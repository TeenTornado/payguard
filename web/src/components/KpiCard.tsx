interface Props {
  label: string
  value: string | number
  sub?: string
  accent?: string
}

export function KpiCard({ label, value, sub, accent }: Props) {
  return (
    <div
      className="panel"
      style={{ padding: '16px 20px', minWidth: 140 }}
    >
      <div style={{ fontSize: '12px', color: '#6B7280', fontWeight: 500, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.02em' }}>
        {label}
      </div>
      <div
        style={{
          fontSize: '24px',
          fontWeight: 600,
          color: accent ?? '#111827',
          lineHeight: 1.2,
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: '12px', color: '#9CA3AF', marginTop: 4 }}>
          {sub}
        </div>
      )}
    </div>
  )
}
