// P3 viewer strings (FE-11). They live here, under the `vw` namespace, because src/i18n/en.json
// belongs to another lane; the integrator moves them into en.json (LANE_NOTES) and deletes this.
import i18n from '../../i18n'

export const VW_EN = {
  loading: 'Loading {{pct}} %',
  loadingBytes: 'Loading {{loaded}} MB',
  decoding: 'Decoding…',
  loadError: 'The image could not be loaded',
  maskError: 'The segmentation could not be loaded',
  errorCode: 'HTTP {{status}} · {{code}}',
  noWebgl: 'This viewer needs WebGL2, which this browser does not provide.',
  slice: 'Slice {{index}} of {{total}}',
  linkZoom: 'Link zoom across views',
  unloaded: 'Unloaded to save memory; it reloads when the tab is shown',
  render: {
    volume: 'Volume render',
    surfaces: 'Label surfaces',
    blend: 'Label blend',
  },
  meshBuilding: 'Building surfaces…',
  meshError: 'Surfaces unavailable',
  harness: {
    title: 'Viewer harness',
    source: 'Source',
    load: 'Load',
    fixture: 'Fixture item',
    reference: 'Reference volume (TST-09)',
  },
}

i18n.addResourceBundle('en', 'translation', { vw: VW_EN }, true, false)
