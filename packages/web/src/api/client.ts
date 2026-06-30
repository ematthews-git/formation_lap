/*
 * Thin typed fetch wrapper over the Formation Lap API.
 *
 * `NotFound` is modelled as a resolved `null` rather than a thrown error, so
 * sections backed by not-yet-populated tables (lap-record, circuit-stats, ...)
 * surface as clean empty states instead of error states.
 */

const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText} — ${path}`)
  }
  return (await res.json()) as T
}

/** GET that treats 404 as "no data yet" → null (not an error). */
async function requestOptional<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(path)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

export const api = { get: request, getOptional: requestOptional }
