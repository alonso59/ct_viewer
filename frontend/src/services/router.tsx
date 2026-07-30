/* eslint-disable react-refresh/only-export-components */
import {
  Children,
  createContext,
  forwardRef,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from 'react'

interface NavigateOptions {
  replace?: boolean
}

interface RouterLocation {
  hash: string
  pathname: string
  search: string
}

interface RouterContextValue {
  navigate: (to: string, options?: NavigateOptions) => void
  path: string
}

interface RouteMatch {
  params: Record<string, string>
  pathname: string
}

interface RouteProps {
  element: ReactNode
  path: string
}

interface MemoryRouterProps {
  children: ReactNode
  initialEntries?: string[]
}

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  replace?: boolean
  to: string
}

const RouterContext = createContext<RouterContextValue | null>(null)
const ParamsContext = createContext<Record<string, string>>({})

export function BrowserRouter({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => getBrowserPath())

  useEffect(() => {
    const handlePopState = () => setPath(getBrowserPath())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = useCallback((to: string, options: NavigateOptions = {}) => {
    if (options.replace) {
      window.history.replaceState(null, '', to)
    } else {
      window.history.pushState(null, '', to)
    }
    setPath(getBrowserPath())
  }, [])

  const value = useMemo(() => ({ navigate, path }), [navigate, path])

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function MemoryRouter({ children, initialEntries = ['/'] }: MemoryRouterProps) {
  const [path, setPath] = useState(() => initialEntries[0] ?? '/')
  const navigate = useCallback((to: string) => setPath(to), [])
  const value = useMemo(() => ({ navigate, path }), [navigate, path])

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function Route(props: RouteProps) {
  void props
  return null
}

export function Routes({ children }: { children: ReactNode }) {
  const location = useLocation()

  for (const child of Children.toArray(children)) {
    if (!isValidElement<RouteProps>(child)) {
      continue
    }

    const match = matchPath(child.props.path, location.pathname)
    if (match) {
      return <ParamsContext.Provider value={match.params}>{child.props.element}</ParamsContext.Provider>
    }
  }

  return null
}

export const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  { onClick, replace = false, target, to, ...props },
  ref,
) {
  const navigate = useNavigate()
  const handleClick = useCallback(
    (event: MouseEvent<HTMLAnchorElement>) => {
      onClick?.(event)
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.altKey ||
        event.ctrlKey ||
        event.shiftKey ||
        (target && target !== '_self')
      ) {
        return
      }

      event.preventDefault()
      navigate(to, { replace })
    },
    [navigate, onClick, replace, target, to],
  )

  return <a {...props} href={to} onClick={handleClick} ref={ref} target={target} />
})

export function matchPath(pattern: string, pathname: string): RouteMatch | null {
  const patternSegments = splitPath(pattern)
  const pathSegments = splitPath(pathname)
  if (patternSegments.length !== pathSegments.length) {
    return null
  }

  const params: Record<string, string> = {}
  for (let index = 0; index < patternSegments.length; index += 1) {
    const patternSegment = patternSegments[index]
    const pathSegment = pathSegments[index]
    if (!patternSegment || !pathSegment) {
      return null
    }
    if (patternSegment.startsWith(':')) {
      params[patternSegment.slice(1)] = decodeURIComponent(pathSegment)
      continue
    }
    if (patternSegment !== pathSegment) {
      return null
    }
  }

  return { params, pathname }
}

export function useLocation(): RouterLocation {
  const { path } = useRouterContext()
  return useMemo(() => parseLocation(path), [path])
}

export function useNavigate() {
  return useRouterContext().navigate
}

export function useParams<
  TParams extends Record<string, string | undefined> = Record<string, string | undefined>,
>(): Partial<TParams> {
  return useContext(ParamsContext) as Partial<TParams>
}

function useRouterContext() {
  const context = useContext(RouterContext)
  if (!context) {
    throw new Error('Router components must be rendered inside BrowserRouter or MemoryRouter')
  }
  return context
}

function getBrowserPath() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

function parseLocation(path: string): RouterLocation {
  const hashIndex = path.indexOf('#')
  const beforeHash = hashIndex === -1 ? path : path.slice(0, hashIndex)
  const hash = hashIndex === -1 ? '' : path.slice(hashIndex)
  const searchIndex = beforeHash.indexOf('?')
  const pathname = searchIndex === -1 ? beforeHash : beforeHash.slice(0, searchIndex)
  const search = searchIndex === -1 ? '' : beforeHash.slice(searchIndex)

  return {
    hash,
    pathname: pathname || '/',
    search,
  }
}

function splitPath(path: string) {
  return path.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean)
}
