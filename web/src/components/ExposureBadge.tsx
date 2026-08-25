import type { ExposureKind } from '@/lib/types'
import { formatPaise } from '@/lib/format'

interface Props {
  kind: ExposureKind
  paise: number | null
}

export function ExposureBadge({ kind, paise }: Props) {
  const amount = paise != null ? formatPaise(paise) : '—'

  if (kind === 'MEASURED') {
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '2px 8px',
          borderRadius: '4px',
          fontSize: '12px',
          fontWeight: 500,
          color: '#344054',
          backgroundColor: '#F8F9FC',
          border: '1px solid #D0D5DD',
          fontFamily: 'JetBrains Mono, monospace',
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: '11px', color: '#6B7280', fontFamily: 'inherit' }}>MEASURED</span>
        <span>{amount}</span>
      </span>
    )
  }

  // ESTIMATED: dashed outline
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '2px 8px',
        borderRadius: '4px',
        fontSize: '12px',
        fontWeight: 500,
        color: '#B54708',
        backgroundColor: '#FFFAEB',
        border: '1px dashed #B54708',
        fontFamily: 'JetBrains Mono, monospace',
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ fontSize: '11px', color: '#B54708', fontFamily: 'inherit' }}>EST.</span>
      <span>{amount}</span>
    </span>
  )
}
