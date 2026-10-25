// Real right-button drag pans only the 3D camera; wheel/orbit/fit stay independent.
// Run with the fixture harness running; HARNESS_URL, CHROME or CDP_URL select server/browser.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const browser = process.env.CDP_URL ? await chromium.connectOverCDP(process.env.CDP_URL) : await chromium.launch({ executablePath: process.env.CHROME || undefined })
try {
  for (const dpr of [1, 2]) {
    const context = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: dpr })
    try {
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', (e) => errors.push(e.message))
      await page.goto(`${process.env.HARNESS_URL || 'http://127.0.0.1:5175'}/src/features/viewer/harness/index.html?case=case_00001&item=case_00001.01.complete.-`)
      await page.waitForFunction(() => performance.getEntriesByName('rw:mask').length > 0, null, { timeout: 60_000 })
      const settle = () => page.waitForTimeout(600)
      await settle()
      const body = page.locator('[data-tile="3d"]')
      const rect = await body.boundingBox()
      const slices = async () => Promise.all(['axial', 'sagittal', 'coronal'].map((p) => page.locator(`[data-tile="${p}"]`).screenshot()))
      const before = await slices()
      const camera = () => page.evaluate(() => {
        const v = window.__viewer, n = v.nv, m = v.renderMatrix, tile = v.tiles.find((t) => t.id === '3d')
        const world = n.frac2mm([0.5, 0.5, 0.5], 0, true)
        const q = [0, 1, 2, 3].map((r) => m[r] * world[0] + m[4+r] * world[1] + m[8+r] * world[2] + m[12+r])
        return { scale: n.scene.volScaleMultiplier, az: n.scene.renderAzimuth, el: n.scene.renderElevation, pan: [...n.pan3d], cross: [...n.scene.crosshairPos], window: [...v.slices.range], point: [(q[0]/q[3]+1)*tile.w/2, (1-q[1]/q[3])*tile.h/2] }
      })
      const initial = await camera()
      const drag = async (button, dx, dy) => {
        await page.mouse.move(rect.x + rect.width/2, rect.y + rect.height/2)
        await page.mouse.down({ button })
        await page.mouse.move(rect.x + rect.width/2 + dx, rect.y + rect.height/2 + dy, { steps: 8 })
        await page.mouse.up({ button })
        await settle()
      }
      await drag('right', 70, 35)
      const moved = await camera()
      assert.ok(Math.abs(moved.point[0] - initial.point[0] - 70) < 1, `Horizontal pan must follow CSS pixels at DPR ${dpr}`)
      assert.ok(Math.abs(moved.point[1] - initial.point[1] - 35) < 1, `Vertical pan must follow CSS pixels at DPR ${dpr}`)
      for (const key of ['scale', 'az', 'el', 'cross', 'window']) assert.deepEqual(moved[key], initial[key], `${key} must not change while panning`)
      const after = await slices()
      after.forEach((image, i) => assert.ok(image.equals(before[i]), `2D slice ${i} changed at DPR ${dpr}`))
      // Release must end the gesture, including motion outside the original drag path.
      await page.mouse.move(rect.x + 20, rect.y + 20)
      await settle()
      assert.deepEqual((await camera()).pan, moved.pan)
      await page.mouse.wheel(0, -120)
      await settle()
      const zoomed = await camera()
      assert.ok(zoomed.scale > moved.scale)
      assert.deepEqual(zoomed.pan, moved.pan)
      await drag('left', 25, 15)
      const orbited = await camera()
      assert.notEqual(orbited.az, zoomed.az)
      assert.deepEqual(orbited.pan, moved.pan)
      await page.getByRole('region', { name: '3D', exact: true }).getByRole('button', { name: 'Fit to window', exact: true }).click()
      await settle()
      const fitted = await camera()
      assert.deepEqual(fitted.pan, [0, 0])
      assert.equal(fitted.scale, 1)
      await drag('right', -30, -20)
      await page.evaluate(() => window.__viewer.resetView())
      await settle()
      assert.deepEqual((await camera()).pan, [0, 0])
      const axial = await page.locator('[data-tile="axial"]').boundingBox()
      const beforeWindow = await camera()
      await page.mouse.move(axial.x + axial.width/2, axial.y + axial.height/2)
      await page.mouse.down({ button: 'right' })
      await page.mouse.move(axial.x + axial.width/2 + 30, axial.y + axial.height/2 + 20, { steps: 4 })
      await page.mouse.up({ button: 'right' })
      await settle()
      const changedWindow = await camera()
      assert.notDeepEqual(changedWindow.window, beforeWindow.window, '2D right-drag must still adjust window/level')
      assert.deepEqual(changedWindow.pan, beforeWindow.pan, '2D window/level must not move the 3D camera')
      assert.equal(await page.evaluate(() => window.__viewer.nv.gl.getError()), 0)
      assert.deepEqual(errors, [])
      console.log(`PASS DPR ${dpr}: right-drag pan, unchanged 2D/zoom/orbit, release, wheel, Fit and Reset`)
    } finally { await context.close() }
  }
} finally { await browser.close() }
