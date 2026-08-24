'use client'

import { useState } from 'react'
import { NewScanDrawer } from './NewScanDrawer'

export function TopBar() {
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <>
      <div
        style={{
          height: 44,
          background: '#fff',
          borderBottom: '1px solid #E5E7EB',
          display: 'flex',
          alignItems: 'center',
          paddingLeft: 20,
          paddingRight: 20,
          gap: 12,
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 100,
        }}
      >
        {/* Wordmark */}
        <span style={{ fontWeight: 700, fontSize: 15, color: '#111827', letterSpacing: '-0.01em', marginRight: 4 }}>
          PayGuard
        </span>

        {/* TEST MODE pill */}
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: '#067647',
            border: '1px solid #067647',
            borderRadius: 4,
            padding: '1px 7px',
            letterSpacing: '0.04em',
          }}
        >
          TEST MODE
        </span>

        {/* Gateway pill */}
        <span
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: '#6B7280',
            border: '1px solid #E5E7EB',
            borderRadius: 4,
            padding: '1px 7px',
          }}
        >
          Razorpay Gateway
        </span>

        <div style={{ flex: 1 }} />

        {/* New scan button */}
        <button
          onClick={() => setDrawerOpen(true)}
          style={{
            height: 30,
            padding: '0 14px',
            background: '#111827',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          New scan
        </button>
      </div>

      <NewScanDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  )
}
