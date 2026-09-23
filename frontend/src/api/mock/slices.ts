// Mid-slices per complete item (from `npm run mock:seed`). Loaded lazily: ~0.6 MB of JSON.
export type Plane = 'axial' | 'coronal' | 'sagittal'
export interface Slice<T extends Int16Array | Uint8Array> {
  w: number
  h: number
  data: T
}
export interface SliceSet {
  image: Record<Plane, Slice<Int16Array>>
  mask: Record<Plane, Slice<Uint8Array>> | null
}

type Raw = { w: number; h: number; b64: string }
type RawSet = { image: Record<Plane, Raw>; mask: Record<Plane, Raw> | null }

function bytes(b64: string): ArrayBuffer {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}
const decode = <T extends Int16Array | Uint8Array>(r: Raw, C: new (b: ArrayBuffer) => T): Slice<T> => ({
  w: r.w,
  h: r.h,
  data: new C(bytes(r.b64)),
})

let cache: Promise<Map<string, SliceSet>> | null = null

export function loadSlices(): Promise<Map<string, SliceSet>> {
  cache ??= import('./slices.json').then((m) => {
    const raw = m.default as unknown as Record<string, RawSet>
    const out = new Map<string, SliceSet>()
    for (const [id, s] of Object.entries(raw)) {
      const planes = ['axial', 'coronal', 'sagittal'] as const
      const image = Object.fromEntries(planes.map((p) => [p, decode(s.image[p], Int16Array)])) as SliceSet['image']
      const mask = s.mask
        ? (Object.fromEntries(planes.map((p) => [p, decode((s.mask as Record<Plane, Raw>)[p], Uint8Array)])) as SliceSet['mask'])
        : null
      out.set(id, { image, mask })
    }
    return out
  })
  return cache
}
