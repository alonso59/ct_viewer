// Command palette ranking (UI-05, AUD-A1-07): title prefix > word prefix > contiguous match >
// keyword / category match > scattered letters. Every search word has to match somewhere.

const words = (s: string) => s.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean)

function subsequence(hay: string, needle: string): boolean {
  let i = 0
  for (const ch of hay) if (ch === needle[i]) i++
  return i === needle.length
}

function tokenScore(token: string, title: string, keywords: string[], category: string): number {
  if (title.startsWith(token)) return 1
  if (words(title).some((w) => w.startsWith(token))) return 0.9
  if (title.includes(token)) return 0.75
  if (keywords.some((k) => words(k).some((w) => w.startsWith(token)))) return 0.7
  if (words(category).some((w) => w.startsWith(token))) return 0.5
  if (keywords.some((k) => k.includes(token)) || category.includes(token)) return 0.4
  if (subsequence(title.replace(/\s+/g, ''), token)) return 0.1
  return 0
}

/** 0 = hidden; higher ranks first. `title` and `category` are the translated texts. */
export function paletteScore(search: string, title: string, keywords: string[] = [], category = ''): number {
  const q = search.trim().toLowerCase()
  if (!q) return 1
  const t = title.toLowerCase()
  const kw = keywords.map((k) => k.toLowerCase())
  const cat = category.toLowerCase()
  if (t === q) return 1
  if (t.startsWith(q)) return 0.99
  let sum = 0
  const tokens = q.split(/\s+/)
  for (const token of tokens) {
    const s = tokenScore(token, t, kw, cat)
    if (s === 0) return 0
    sum += s
  }
  // Stay below the whole-title prefix matches above
  return Math.min(0.98, sum / tokens.length)
}
