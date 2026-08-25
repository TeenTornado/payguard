import { LeftNav } from '@/components/LeftNav'
import { TopBar } from '@/components/TopBar'
import './globals.css'

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <title>PayGuard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body style={{ margin: 0, background: '#F6F7F9', fontFamily: 'Inter, system-ui, sans-serif' }}>
        <TopBar />
        <LeftNav />
        <main
          style={{
            marginLeft: 220,
            marginTop: 44,
            padding: '24px',
            minHeight: 'calc(100vh - 44px)',
          }}
        >
          {children}
        </main>
      </body>
    </html>
  )
}
