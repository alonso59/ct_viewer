// App logo (UI-21): static PNGs in public/brand/, outside the JS bundle (NFR-07).
// Master artwork: docs/brand/logo-master.png. Never recolour, crop or stretch it.
const BASE = `${import.meta.env.BASE_URL}brand/`

export function BrandMark({ size = 20, alt = '' }: { size?: number; alt?: string }) {
  // 1x / 2x sources; 32 px covers ≤ 16 px at 2x, 64 px ≤ 32 px, 128 px anything larger
  const src = size <= 16 ? 'logo-32.png' : size <= 32 ? 'logo-64.png' : 'logo-128.png'
  return (
    <img
      className="brand-mark"
      src={BASE + src}
      width={size}
      height={size}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      draggable={false}
      decoding="async"
    />
  )
}
