import '@testing-library/jest-dom/vitest'

globalThis.URL.createObjectURL = globalThis.URL.createObjectURL ?? (() => 'blob:test')
globalThis.URL.revokeObjectURL = globalThis.URL.revokeObjectURL ?? (() => {})
globalThis.scrollTo = () => {}
