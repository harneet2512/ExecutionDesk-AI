import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import AppShell from '@/components/AppShell'
import { BRAND } from '@/src/config/brand'

// Single font for sharpness; avoid duplicate next/font imports
const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: BRAND.name,
  description: `${BRAND.name} – ${BRAND.tagline}`,
  applicationName: BRAND.name,
  openGraph: {
    title: BRAND.name,
    description: `${BRAND.name} – ${BRAND.tagline}`,
  },
  twitter: {
    title: BRAND.name,
    description: `${BRAND.name} – ${BRAND.tagline}`,
  },
  manifest: '/manifest.webmanifest',
  icons: {
    icon: [
      { url: '/executivedesk-favicon.svg', type: 'image/svg+xml' },
      { url: '/favicon.ico', sizes: 'any' },
    ],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  )
}
