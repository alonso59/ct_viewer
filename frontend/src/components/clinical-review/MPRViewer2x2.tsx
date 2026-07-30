import type { ComponentProps } from 'react'

import ViewerGrid2x2 from '../viewer/ViewerGrid2x2'

type MPRViewer2x2Props = Pick<ComponentProps<typeof ViewerGrid2x2>, 'legend' | 'panels'>

function MPRViewer2x2({ legend, panels }: MPRViewer2x2Props) {
  return <ViewerGrid2x2 layout="cockpit" legend={legend} panels={panels} />
}

export default MPRViewer2x2
