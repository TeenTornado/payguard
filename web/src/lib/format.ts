/**
 * Format paise (integer) to Indian rupee string.
 * 150000 paise → ₹1,50,000.00
 */
export function formatPaise(paise: number): string {
  const rupees = paise / 100
  // Indian number system: last 3 digits then groups of 2
  const [intPart, decPart] = rupees.toFixed(2).split('.')
  const formatted = formatIndianNumber(intPart)
  return `₹${formatted}.${decPart}`
}

function formatIndianNumber(numStr: string): string {
  const negative = numStr.startsWith('-')
  const digits = negative ? numStr.slice(1) : numStr

  if (digits.length <= 3) {
    return negative ? `-${digits}` : digits
  }

  // Last 3 digits as the first group, then groups of 2 from right
  const lastThree = digits.slice(-3)
  const remaining = digits.slice(0, -3)

  // Split remaining into groups of 2 from the right
  const groups: string[] = []
  let i = remaining.length
  while (i > 0) {
    const start = Math.max(i - 2, 0)
    groups.unshift(remaining.slice(start, i))
    i = start
  }

  const result = groups.length > 0 ? `${groups.join(',')},${lastThree}` : lastThree
  return negative ? `-${result}` : result
}

/**
 * Format ISO timestamp to human-readable.
 * e.g. "21 Aug 2026, 14:32"
 */
export function formatDate(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/**
 * Format ISO timestamp to date only.
 * e.g. "21 Aug 2026"
 */
export function formatDateOnly(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Format duration between two ISO timestamps.
 * e.g. "2m 34s"
 */
export function formatDuration(start: string, end: string | null): string {
  if (!end) return '—'
  const startMs = new Date(start).getTime()
  const endMs = new Date(end).getTime()
  if (isNaN(startMs) || isNaN(endMs)) return '—'
  const seconds = Math.floor((endMs - startMs) / 1000)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}m ${secs}s`
}

/**
 * Truncate a hash to first 8 chars + ellipsis.
 */
export function truncateHash(hash: string): string {
  if (!hash) return '—'
  return hash.slice(0, 8) + '…'
}

/**
 * Format a floating point score as a percentage string.
 */
export function formatPct(val: number): string {
  return (val * 100).toFixed(1) + '%'
}
