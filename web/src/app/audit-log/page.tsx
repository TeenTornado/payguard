'use client'

import { AuditLogTable } from '@/components/AuditLogTable'

export default function AuditLogPage() {
  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 20 }}>
        Audit Log
      </div>
      <AuditLogTable />
    </div>
  )
}
