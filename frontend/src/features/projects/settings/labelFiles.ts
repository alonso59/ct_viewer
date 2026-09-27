// Label map import (PRJ-18 Labels tab): 3D Slicer colour tables (`.ctbl` / `.txt`), ITK-SNAP label
// descriptions and nnU-Net `dataset.json`. Pure parsers → LabelDef[]; background (0) is skipped.
import type { LabelDef } from '../../../api'
import { autoLabelColor } from '../../../theme'

export type LabelFileKind = 'slicer' | 'itksnap' | 'nnunet'

const hex = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0').toUpperCase()
const rgb = (r: number, g: number, b: number) => `#${hex(r)}${hex(g)}${hex(b)}`
const auto = autoLabelColor

function label(value: number, name: string, color: string, opacity = 0.2, visible = true): LabelDef {
  return { value, name: name.trim() || `label_${value}`, color, opacity: Math.max(0, Math.min(1, opacity)), visible }
}

/** 3D Slicer colour table: `value name R G B A` per line (0–255), `#` comments. */
export function parseSlicer(text: string): LabelDef[] {
  const out: LabelDef[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const parts = line.split(/\s+/)
    const value = Number(parts[0])
    if (!Number.isInteger(value) || value <= 0 || parts.length < 5) continue
    const [r, g, b, a] = parts.slice(2, 6).map(Number)
    out.push(label(value, parts[1] ?? '', rgb(r ?? 255, g ?? 255, b ?? 255), a == null || Number.isNaN(a) ? 0.2 : Math.min(1, (a / 255) * 0.3)))
  }
  return out
}

/** ITK-SNAP label description: `IDX R G B A VIS MSH "LABEL"`; A is 0–1, VIS 0/1. */
export function parseItkSnap(text: string): LabelDef[] {
  const out: LabelDef[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const m = /^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d)\s+(\d)\s+"(.*)"\s*$/.exec(line)
    if (!m) continue
    const value = Number(m[1])
    if (value <= 0) continue
    out.push(label(value, m[8] ?? '', rgb(Number(m[2]), Number(m[3]), Number(m[4])), Math.min(1, Number(m[5]) * 0.3), m[6] !== '0'))
  }
  return out
}

/** nnU-Net `dataset.json`: v2 `labels: {name: value}` (region lists skipped) or v1 `{"1": name}`. */
export function parseNnunet(text: string): LabelDef[] {
  const doc = JSON.parse(text) as { labels?: Record<string, unknown> }
  const labels = doc.labels ?? {}
  const pairs: [number, string][] = []
  for (const [k, v] of Object.entries(labels)) {
    if (typeof v === 'number') pairs.push([v, k])
    else if (typeof v === 'string' && /^\d+$/.test(k)) pairs.push([Number(k), v])
  }
  return pairs
    .filter(([value]) => Number.isInteger(value) && value > 0)
    .sort((a, b) => a[0] - b[0])
    .map(([value, name]) => label(value, name, auto(value)))
}

export function detectKind(fileName: string, text: string): LabelFileKind | null {
  if (/\.json$/i.test(fileName) || text.trimStart().startsWith('{')) return 'nnunet'
  if (/^\s*\d+\s+\d+\s+\d+\s+\d+\s+[\d.]+\s+\d\s+\d\s+"/m.test(text)) return 'itksnap'
  if (/\.(ctbl|txt)$/i.test(fileName) || /^\s*\d+\s+\S+\s+\d+\s+\d+\s+\d+/m.test(text)) return 'slicer'
  return null
}

export function parseLabelFile(fileName: string, text: string): { kind: LabelFileKind; labels: LabelDef[] } {
  const kind = detectKind(fileName, text)
  if (!kind) throw new Error('unrecognized')
  const labels = kind === 'nnunet' ? parseNnunet(text) : kind === 'itksnap' ? parseItkSnap(text) : parseSlicer(text)
  if (!labels.length) throw new Error('empty')
  return { kind, labels }
}

/** Imported labels replace entries with the same value; the others are kept (nothing deleted). */
export function mergeLabels(current: LabelDef[], incoming: LabelDef[]): LabelDef[] {
  const byValue = new Map(current.map((l) => [l.value, l]))
  for (const l of incoming) byValue.set(l.value, l)
  return [...byValue.values()].sort((a, b) => a.value - b.value)
}
