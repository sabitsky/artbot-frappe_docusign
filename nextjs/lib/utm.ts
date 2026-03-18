// lib/utm.ts
// Server-side only (uses next/headers).
// Copy this file into your Next.js project at lib/utm.ts

import { cookies } from "next/headers"

const UTM_COOKIE = "utm_data"

export interface UtmData {
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
}

/**
 * Read UTM data from cookie (server-side only).
 * NOTE: In Next.js 15+ cookies() is async. In Next.js 14 — remove await.
 */
export async function getUtmFromCookie(): Promise<UtmData> {
  const cookieStore = await cookies()
  const raw = cookieStore.get(UTM_COOKIE)?.value
  if (!raw) return {}
  try {
    return JSON.parse(raw) as UtmData
  } catch {
    return {}
  }
}
