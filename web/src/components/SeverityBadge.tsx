import type { Severity } from '@/lib/types'

const colorMap: Record<Severity, string> = {
  CRITICAL: '#B42318',
  HIGH: '#C4320A',
  MEDIUM: '#B54708',
  LOW: '#475467',
}

const bgMap: Record<Severity, string> = {
  CRITICAL: '#FEF3F2',
  HIGH: '#FFF4ED',
  MEDIUM: '#FFFAEB',
  LOW: '#F8F9FC',
}

interface Props {
  severity: Severity
  size?: 'sm' | 'md'
}

export function SeverityBadge({ severity, size = 'md' }: Props) {
  const color = colorMap[severity] ?? '#6B7280'
  const bg = bgMap[severity] ?? '#F3F4F6'
  const px = size === 'sm' ? '6px' : '8px'
  const py = size === 'sm' ? '1px' : '2px'
  const fontSize = size === 'sm' ? '11px' : '12px'

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: `${py} ${px}`,
        borderRadius: '4px',
        fontSize,
        fontWeight: 500,
        color,
        backgroundColor: bg,
        border: `1px solid ${color}22`,
        lineHeight: 1.4,
        whiteSpace: 'nowrap',
      }}
    >
      {severity}
    </span>
  )
}
