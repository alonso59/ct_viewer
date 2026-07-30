import '@testing-library/jest-dom/vitest'

globalThis.URL.createObjectURL = globalThis.URL.createObjectURL ?? (() => 'blob:test')
globalThis.URL.revokeObjectURL = globalThis.URL.revokeObjectURL ?? (() => {})
globalThis.scrollTo = () => {}

globalThis.requestAnimationFrame =
  globalThis.requestAnimationFrame ??
  ((callback: FrameRequestCallback) => window.setTimeout(() => callback(performance.now()), 0))
globalThis.cancelAnimationFrame =
  globalThis.cancelAnimationFrame ?? ((handle: number) => window.clearTimeout(handle))

globalThis.ResizeObserver =
  globalThis.ResizeObserver ??
  class ResizeObserver {
    private callback: ResizeObserverCallback

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback
    }

    observe(target: Element) {
      const rect = target.getBoundingClientRect()
      this.callback(
        [
          {
            target,
            contentRect: rect,
          } as ResizeObserverEntry,
        ],
        this,
      )
    }

    unobserve() {}

    disconnect() {}
  }
