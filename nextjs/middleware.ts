// middleware.ts
// Place in the root of your Next.js project (same level as app/).
// Captures UTM params from URL on first visit and stores them in a cookie.

import { NextRequest, NextResponse } from "next/server"

const UTM_COOKIE = "utm_data"
const UTM_PARAMS = ["utm_source", "utm_medium", "utm_campaign"]

export function middleware(req: NextRequest) {
  const res = NextResponse.next()
  const url = req.nextUrl

  // Save UTM params to cookie only on first visit (don't overwrite existing)
  const hasUtm = UTM_PARAMS.some((p) => url.searchParams.has(p))
  const alreadySet = req.cookies.has(UTM_COOKIE)

  if (hasUtm && !alreadySet) {
    const utm: Record<string, string> = {}
    UTM_PARAMS.forEach((p) => {
      const v = url.searchParams.get(p)
      if (v) utm[p] = v
    })
    res.cookies.set(UTM_COOKIE, JSON.stringify(utm), {
      maxAge: 60 * 60 * 24 * 30, // 30 days
      httpOnly: true,
      sameSite: "lax",
    })
  }

  return res
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
}
