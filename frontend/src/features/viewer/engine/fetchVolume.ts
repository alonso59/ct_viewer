// Download a volume once with byte progress (VW-13). gzip bodies are inflated while they stream
// (native DecompressionStream), so decoding overlaps the download instead of following it.
import type { LoadProgress } from '../model/types'

export class VolumeFetchError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    message: string,
  ) {
    super(message)
  }
}

async function problem(res: Response): Promise<VolumeFetchError> {
  let code: string | null = null
  let title = res.statusText
  try {
    const body = (await res.json()) as { type?: string; title?: string; code?: string }
    code = body.code ?? body.type?.split('/').pop() ?? null
    title = body.title ?? title
  } catch {
    // not problem+json
  }
  return new VolumeFetchError(res.status, code, title || `HTTP ${res.status}`)
}

/** Returns the uncompressed bytes and whether the payload was gzip */
export async function fetchVolume(url: string, onProgress?: (p: LoadProgress) => void, signal?: AbortSignal): Promise<{ bytes: ArrayBuffer; gzip: boolean }> {
  const res = await fetch(url, { signal })
  if (!res.ok) throw await problem(res)
  const len = Number(res.headers.get('content-length'))
  const total = Number.isFinite(len) && len > 0 ? len : null
  const body = res.body
  if (!body) return { bytes: await res.arrayBuffer(), gzip: false }

  const reader = body.getReader()
  const first = await reader.read()
  const head = first.value ?? new Uint8Array()
  const gzip = head[0] === 0x1f && head[1] === 0x8b
  let loaded = head.byteLength
  onProgress?.({ loaded, total })
  let last = 0
  const counted = new ReadableStream<Uint8Array>({
    start(c) {
      if (head.byteLength) c.enqueue(head)
      if (first.done) c.close()
    },
    async pull(c) {
      const { done, value } = await reader.read()
      if (done) {
        onProgress?.({ loaded, total })
        c.close()
        return
      }
      loaded += value.byteLength
      const now = performance.now()
      if (now - last > 50) {
        last = now
        onProgress?.({ loaded, total })
      }
      c.enqueue(value)
    },
    cancel(reason) {
      void reader.cancel(reason)
    },
  })
  const stream = gzip ? counted.pipeThrough(new DecompressionStream('gzip') as unknown as ReadableWritablePair<Uint8Array, Uint8Array>) : counted
  return { bytes: await new Response(stream).arrayBuffer(), gzip }
}
