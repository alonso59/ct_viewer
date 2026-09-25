// PRJ-17: a view-only workbench uses the pseudo project id `view-{token}`; its reads go to the
// read-only mirror `/api/v1/view/{token}/…` (API-60), which has no write routes.
export const VIEW_PREFIX = 'view-'
export const viewPid = (token: string) => `${VIEW_PREFIX}${token}`
export const isViewPid = (pid: string | null | undefined) => !!pid && pid.startsWith(VIEW_PREFIX)
export const viewPath = (url: string) =>
  url
    .replace(/\/api\/v1\/projects\/view-([A-Za-z0-9_-]+)(?=\/|\?|$)/, '/api/v1/view/$1')
    .replace(/\/api\/v1\/plugins\/labeling\/projects\/view-([A-Za-z0-9_-]+)\//, '/api/v1/view/$1/plugins/labeling/')
    // the project's jobs, without its project_id (API-60, AUD-A5-03)
    .replace(/\/api\/v1\/jobs\?project=view-([A-Za-z0-9_-]+)$/, '/api/v1/view/$1/jobs')
