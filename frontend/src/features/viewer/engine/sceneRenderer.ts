// Scene decorations use the same world-to-camera matrix as the volume, including screenshots.
import { hexToRgb } from '../model/labels'
import { PLANE_AXIS, PLANES } from '../model/layouts'
import { planeCorners } from '../model/scene3d'
import type { Scene3DOptions, Vec3 } from '../model/types'
import { apply, type Mat } from './volumeMath'
import { glProgram, withGLState } from './glProgram'

const BACK_VERTEX = `#version 300 es
out vec2 uv;
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  uv = p;
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`
const BACK_FRAGMENT = `#version 300 es
precision highp float;
in vec2 uv;
uniform vec3 bottomColor, topColor;
out vec4 color;
void main() { color = vec4(mix(bottomColor, topColor, uv.y), 1.0); }`
const LINE_VERTEX = `#version 300 es
layout(location=0) in vec3 point;
uniform mat4 mvp;
void main() { gl_Position = mvp * vec4(point, 1.0); }`
const LINE_FRAGMENT = `#version 300 es
precision highp float;
uniform vec4 lineColor;
out vec4 color;
void main() { color = lineColor; }`

export class SceneRenderer {
  readonly emptyVolume: WebGLTexture
  private backgroundProgram: WebGLProgram
  private lineProgram: WebGLProgram
  private backgroundVao: WebGLVertexArrayObject
  private vao: WebGLVertexArrayObject
  private buffer: WebGLBuffer
  private colors: Record<string, number[]>

  constructor(private gl: WebGL2RenderingContext, canvas: HTMLCanvasElement) {
    this.backgroundProgram = glProgram(gl, BACK_VERTEX, BACK_FRAGMENT)
    this.lineProgram = glProgram(gl, LINE_VERTEX, LINE_FRAGMENT)
    this.backgroundVao = gl.createVertexArray()!
    this.vao = gl.createVertexArray()!
    this.buffer = gl.createBuffer()!
    this.emptyVolume = gl.createTexture()!
    gl.activeTexture(gl.TEXTURE15)
    gl.bindTexture(gl.TEXTURE_3D, this.emptyVolume)
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA8, 1, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4))
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    gl.activeTexture(gl.TEXTURE0)
    const css = getComputedStyle(canvas)
    this.colors = Object.fromEntries(PLANES.map((p) => [p, [...hexToRgb(css.getPropertyValue(`--plane-${p}`).trim()).map((c) => c / 255), 1]]))
  }

  background(kind: Scene3DOptions['background']) {
    const gl = this.gl
    withGLState(gl, () => {
      gl.disable(gl.DEPTH_TEST)
      gl.disable(gl.CULL_FACE)
      gl.disable(gl.BLEND)
      gl.depthMask(false)
      gl.bindVertexArray(this.backgroundVao)
      gl.useProgram(this.backgroundProgram)
      // 3D Slicer vtkMRMLViewNode defaults (RGB 193/195/232 → 116/120/190).
      const bottom = kind === 'slicer' ? [193 / 255, 195 / 255, 232 / 255] : kind === 'white' ? [1, 1, 1] : [0, 0, 0]
      const top = kind === 'slicer' ? [116 / 255, 120 / 255, 190 / 255] : bottom
      gl.uniform3fv(gl.getUniformLocation(this.backgroundProgram, 'bottomColor'), bottom)
      gl.uniform3fv(gl.getUniformLocation(this.backgroundProgram, 'topColor'), top)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
    })
  }

  guides(mvp: Float32Array, fracToMM: Mat, cross: Vec3, scene: Scene3DOptions) {
    const gl = this.gl
    const segment = (a: Vec3, b: Vec3, color: number[]) => {
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([...apply(fracToMM, a), ...apply(fracToMM, b)]), gl.STREAM_DRAW)
      gl.uniform4fv(gl.getUniformLocation(this.lineProgram, 'lineColor'), color)
      gl.drawArrays(gl.LINES, 0, 2)
    }
    withGLState(gl, () => {
      gl.useProgram(this.lineProgram)
      gl.uniformMatrix4fv(gl.getUniformLocation(this.lineProgram, 'mvp'), false, mvp)
      gl.bindVertexArray(this.vao)
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer)
      gl.enableVertexAttribArray(0)
      gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0)
      gl.disable(gl.DEPTH_TEST)
      gl.disable(gl.CULL_FACE)
      gl.depthMask(false)
      gl.enable(gl.BLEND)
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
      for (const plane of PLANES) {
        const axis = PLANE_AXIS[plane]
        if (scene.bounds) {
          for (const [u, v] of [[0, 0], [0, 1], [1, 0], [1, 1]]) {
            const other = ([0, 1, 2] as const).filter((a) => a !== axis)
            const a: Vec3 = [0, 0, 0]
            a[other[0]!] = u!; a[other[1]!] = v!
            const b = [...a] as Vec3; b[axis] = 1
            segment(a, b, [1, 0, 1, 0.55])
          }
        }
        if (scene.axes) {
          const a = [...cross] as Vec3; a[axis] = 0
          const b = [...cross] as Vec3; b[axis] = 1
          segment(a, b, this.colors[plane]!)
        }
        if (scene.planes[plane] !== 'off') {
          const corners = planeCorners(axis, cross[axis])
          for (let i = 0; i < 4; i++) segment(corners[i]!, corners[(i + 1) % 4]!, this.colors[plane]!)
        }
      }
    })
  }

  dispose() {
    const gl = this.gl
    gl.deleteProgram(this.backgroundProgram)
    gl.deleteProgram(this.lineProgram)
    gl.deleteVertexArray(this.backgroundVao)
    gl.deleteVertexArray(this.vao)
    gl.deleteBuffer(this.buffer)
    gl.deleteTexture(this.emptyVolume)
  }
}
