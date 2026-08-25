interface Props {
  lines: string[]
  highlightStart: number // 1-based
  highlightEnd: number   // 1-based
  file?: string
  contextLines?: number
}

export function CodeViewer({ lines, highlightStart, highlightEnd, file, contextLines = 15 }: Props) {
  // Compute visible window: ±contextLines around the highlighted region
  const firstLine = 1
  const lastLine = lines.length
  const windowStart = Math.max(firstLine, highlightStart - contextLines)
  const windowEnd = Math.min(lastLine, highlightEnd + contextLines)

  const visibleLines = lines.slice(windowStart - 1, windowEnd)

  return (
    <div
      style={{
        background: '#0F172A',
        borderRadius: 6,
        overflow: 'hidden',
        border: '1px solid #1E293B',
      }}
    >
      {file && (
        <div
          style={{
            padding: '6px 14px',
            background: '#1E293B',
            fontSize: 12,
            color: '#94A3B8',
            fontFamily: 'JetBrains Mono, monospace',
            borderBottom: '1px solid #334155',
          }}
        >
          {file}
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: 'auto', minWidth: '100%' }}>
          <tbody>
            {visibleLines.map((line, idx) => {
              const lineNum = windowStart + idx
              const isHighlighted = lineNum >= highlightStart && lineNum <= highlightEnd
              return (
                <tr
                  key={lineNum}
                  style={{
                    background: isHighlighted ? '#3B2B00' : 'transparent',
                  }}
                >
                  <td
                    style={{
                      padding: '1px 16px 1px 14px',
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: 12,
                      color: '#475569',
                      userSelect: 'none',
                      verticalAlign: 'top',
                      whiteSpace: 'nowrap',
                      borderBottom: 'none',
                      textAlign: 'right',
                      minWidth: 44,
                    }}
                  >
                    {lineNum}
                  </td>
                  <td
                    style={{
                      padding: '1px 14px 1px 0',
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: 12,
                      color: isHighlighted ? '#FCD34D' : '#CBD5E1',
                      whiteSpace: 'pre',
                      verticalAlign: 'top',
                      borderBottom: 'none',
                    }}
                  >
                    {isHighlighted && (
                      <span style={{ color: '#F59E0B', marginRight: 8, userSelect: 'none' }}>›</span>
                    )}
                    {line}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
