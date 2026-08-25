'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV_ITEMS = [
  { label: 'Overview', href: '/' },
  { label: 'Scans', href: '/scans' },
  { label: 'Findings', href: '/findings' },
  { label: 'Exception Queue', href: '/exception-queue' },
  { label: 'Audit Log', href: '/audit-log' },
  { label: 'Evaluation', href: '/evaluation' },
  { label: 'Settings', href: '/settings' },
]

export function LeftNav() {
  const pathname = usePathname()

  return (
    <nav
      style={{
        width: 220,
        background: '#fff',
        borderRight: '1px solid #E5E7EB',
        position: 'fixed',
        top: 44,
        bottom: 0,
        left: 0,
        overflowY: 'auto',
        padding: '12px 0',
        zIndex: 90,
      }}
    >
      {NAV_ITEMS.map((item) => {
        const isActive =
          item.href === '/'
            ? pathname === '/'
            : pathname === item.href || pathname.startsWith(item.href + '/')

        return (
          <Link
            key={item.href}
            href={item.href}
            style={{
              display: 'block',
              padding: '7px 20px',
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              color: isActive ? '#111827' : '#6B7280',
              background: isActive ? '#F6F7F9' : 'transparent',
              borderRight: isActive ? '2px solid #111827' : '2px solid transparent',
              textDecoration: 'none',
              cursor: 'pointer',
            }}
          >
            {item.label}
          </Link>
        )
      })}
    </nav>
  )
}
