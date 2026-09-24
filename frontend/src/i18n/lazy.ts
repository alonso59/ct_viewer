// Strings used only inside lazy chunks (dashboard, analysis, queue editor) load with those chunks,
// not the initial bundle (FE-05, NFR-07). Deep-merged into the same `translation` namespace, so keys
// keep their names (`dashboard.*`, `analysis.*`, `queue.*`). Import for side effects.
import i18n from './index'
import bundle from './en.lazy.json'

i18n.addResourceBundle('en', 'translation', bundle, true, false)
