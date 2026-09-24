// The viewer without a project tab (Open mode, SRC-09 / VW-21): same surface, no curation or tasks.
import type { ItemRecord, LabelDef } from '../../api'
import { ViewerSurface } from './ViewerSurface'
import './viewer.css'

export function StandaloneViewer({ item, imageUrl, maskUrl, labels }: { item: ItemRecord; imageUrl: string; maskUrl?: string; labels: LabelDef[] }) {
  return (
    <div className="case-editor" tabIndex={-1}>
      <ViewerSurface item={item} imageUrl={imageUrl} maskUrl={maskUrl} labels={labels} active loaded />
    </div>
  )
}
