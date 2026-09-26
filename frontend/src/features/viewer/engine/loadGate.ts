// VW-14/15 load ordering (AUD-A5-13): each load or mesh update takes a ticket; after every await
// it checks that it is still the latest and that its signal is not aborted, so an older load that
// finishes last never replaces the newer image and a repeated `setMeshes` never adds a mesh twice.

/** Thrown when a ticket's signal was aborted (callers ignore it like a fetch abort) */
export const abortError = () => new DOMException('The load was superseded', 'AbortError')

export interface Ticket {
  /** true while this is the newest ticket, the gate is open and the signal is not aborted */
  readonly live: () => boolean
  /** Throws `AbortError` once aborted; returns false when superseded (the caller stops quietly) */
  readonly check: () => boolean
}

export class LoadGate {
  private n = 0
  private closed = false

  begin(signal?: AbortSignal): Ticket {
    const mine = ++this.n
    const live = () => !this.closed && mine === this.n && !signal?.aborted
    return {
      live,
      check: () => {
        if (signal?.aborted) throw abortError()
        return live()
      },
    }
  }

  /** The newest ticket's number (a mesh set belongs to the image load it was made for) */
  get current(): number {
    return this.n
  }

  close(): void {
    this.closed = true
  }
}
