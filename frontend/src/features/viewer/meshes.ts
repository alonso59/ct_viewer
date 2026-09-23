// API-25 client: `202` + job while the mesh builds, then the cached gzip MZ3 (VW-09).
export class MeshUnavailable extends Error {}

/** Resolves with the mesh bytes, polling while the backend job runs (≤ `timeoutMs`). */
export async function fetchMesh(url: string, signal?: AbortSignal, timeoutMs = 60_000): Promise<ArrayBuffer> {
  const t0 = performance.now()
  let wait = 250
  for (;;) {
    const res = await fetch(url, { signal })
    if (res.status === 200) return res.arrayBuffer()
    if (res.status !== 202) throw new MeshUnavailable(`HTTP ${res.status}`)
    const job = (await res.json()) as { status?: string; error?: string | null }
    if (job.status === 'failed' || job.status === 'cancelled') throw new MeshUnavailable(job.error ?? job.status)
    if (performance.now() - t0 > timeoutMs) throw new MeshUnavailable('timeout')
    await new Promise((r) => setTimeout(r, wait))
    wait = Math.min(2000, wait * 1.5)
  }
}
