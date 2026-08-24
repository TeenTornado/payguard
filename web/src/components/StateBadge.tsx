import type { FindingState, ScanState, VerificationStatus } from '@/lib/types'

type StateValue = FindingState | ScanState | VerificationStatus | string

interface BadgeStyle {
  color: string
  bg: string
  border: string
}

function getStyle(state: StateValue): BadgeStyle {
  switch (state) {
    case 'VERIFIED':
      return { color: '#067647', bg: '#ECFDF3', border: '#06764722' }
    case 'NOT_REPRODUCED':
      return { color: '#6B7280', bg: '#F3F4F6', border: '#6B728022' }
    case 'INCONCLUSIVE':
      return { color: '#B54708', bg: '#FFFAEB', border: '#B5470822' }
    case 'BLOCKED':
    case 'ERROR':
    case 'FAILED':
      return { color: '#B42318', bg: '#FFF8F8', border: '#B42318' }
    case 'ADVISORY':
      return { color: '#344054', bg: '#F8F9FC', border: '#34405422' }
    case 'DONE':
      return { color: '#067647', bg: '#ECFDF3', border: '#06764722' }
    case 'QUEUED_FOR_VERIFICATION':
      return { color: '#344054', bg: '#F8F9FC', border: '#34405422' }
    case 'DISMISSED':
      return { color: '#9CA3AF', bg: '#F9FAFB', border: '#9CA3AF22' }
    case 'EXCEPTION':
      return { color: '#B54708', bg: '#FFFAEB', border: '#B5470822' }
    case 'UNVERIFIED':
      return { color: '#6B7280', bg: '#F3F4F6', border: '#6B728022' }
    case 'INGEST':
    case 'DISCOVER':
    case 'STATIC':
    case 'SEMANTIC':
    case 'NORMALIZE':
    case 'SCORE':
    case 'SELECT_SCENARIOS':
    case 'VERIFY':
    case 'DECIDE':
    case 'HUMAN_GATE':
    case 'REMEDIATE':
      return { color: '#1D4ED8', bg: '#EFF6FF', border: '#1D4ED822' }
    default:
      return { color: '#6B7280', bg: '#F3F4F6', border: '#6B728022' }
  }
}

interface Props {
  state: StateValue
  size?: 'sm' | 'md'
  outlined?: boolean
}

export function StateBadge({ state, size = 'md', outlined = false }: Props) {
  const style = getStyle(state)
  const isError = state === 'BLOCKED' || state === 'ERROR' || state === 'FAILED'
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
        color: style.color,
        backgroundColor: style.bg,
        border: isError || outlined ? `1px solid ${style.border}` : `1px solid ${style.border}`,
        lineHeight: 1.4,
        whiteSpace: 'nowrap',
      }}
    >
      {state.replace(/_/g, ' ')}
    </span>
  )
}
