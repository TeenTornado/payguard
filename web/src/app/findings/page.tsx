'use client'

import { FindingsTable } from '@/components/FindingsTable'

export default function FindingsPage() {
  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>
        Findings
      </div>
      <FindingsTable showFilters={true} />
    </div>
  )
}
