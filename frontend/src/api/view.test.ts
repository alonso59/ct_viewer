// PRJ-17 / API-60: a view-only workbench reads only through `/view/{token}/…` (AUD-A5-03).
import { viewPath } from './view'

test('project, labeling and job reads of a view pid go to the read-only mirror', () => {
  expect(viewPath('/api/v1/projects/view-Ab_9/cases?limit=1')).toBe('/api/v1/view/Ab_9/cases?limit=1')
  expect(viewPath('/api/v1/projects/view-Ab_9')).toBe('/api/v1/view/Ab_9')
  expect(viewPath('/api/v1/plugins/labeling/projects/view-Ab_9/tables')).toBe('/api/v1/view/Ab_9/plugins/labeling/tables')
  expect(viewPath('http://h/api/v1/jobs?project=view-Ab_9')).toBe('http://h/api/v1/view/Ab_9/jobs')
})

test('other URLs are unchanged', () => {
  for (const u of ['/api/v1/projects/01ABC/cases', '/api/v1/jobs?project=01ABC', '/api/v1/jobs']) expect(viewPath(u)).toBe(u)
})
