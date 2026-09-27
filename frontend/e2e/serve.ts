// `make e2e-servers`: start the E2E backend and web server in the foreground on the fixed reuse
// folders, for `E2E_REUSE=1 make e2e-one SPEC=…` loops (AUD-A6-18). Ctrl-C stops both.
import { spawn } from 'node:child_process'

process.env.E2E_REUSE = '1'
const { serverCommands } = await import('./servers.ts')
const procs = serverCommands().map(({ name, command }) => {
  const p = spawn(command, { shell: true, stdio: 'inherit' })
  p.on('exit', (code) => {
    console.log(`e2e-servers: ${name} exited (${code})`)
    process.exit(code ?? 1)
  })
  return p
})
process.on('SIGINT', () => procs.forEach((p) => p.kill('SIGTERM')))
