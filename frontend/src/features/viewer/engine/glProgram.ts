// Small engine-owned programs share the NiiVue WebGL2 context.
export function glProgram(gl: WebGL2RenderingContext, vertex: string, fragment: string): WebGLProgram {
  const program = gl.createProgram()!
  for (const [type, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]] as const) {
    const shader = gl.createShader(type)!
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const error = gl.getShaderInfoLog(shader)
      gl.deleteShader(shader)
      gl.deleteProgram(program)
      throw new Error(`Viewer shader: ${error}`)
    }
    gl.attachShader(program, shader)
    gl.deleteShader(shader)
  }
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const error = gl.getProgramInfoLog(program)
    gl.deleteProgram(program)
    throw new Error(`Viewer program: ${error}`)
  }
  return program
}

export function withGLState(gl: WebGL2RenderingContext, draw: () => void): void {
  const program = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram | null
  const vao = gl.getParameter(gl.VERTEX_ARRAY_BINDING) as WebGLVertexArrayObject | null
  const buffer = gl.getParameter(gl.ARRAY_BUFFER_BINDING) as WebGLBuffer | null
  const depth = gl.isEnabled(gl.DEPTH_TEST)
  const cull = gl.isEnabled(gl.CULL_FACE)
  const blend = gl.isEnabled(gl.BLEND)
  const write = gl.getParameter(gl.DEPTH_WRITEMASK) as boolean
  const activeTexture = gl.getParameter(gl.ACTIVE_TEXTURE) as number
  const blendFactors = [gl.BLEND_SRC_RGB, gl.BLEND_DST_RGB, gl.BLEND_SRC_ALPHA, gl.BLEND_DST_ALPHA].map((p) => gl.getParameter(p) as number)
  const depthFunc = gl.getParameter(gl.DEPTH_FUNC) as number
  try { draw() } finally {
    gl.useProgram(program)
    gl.bindVertexArray(vao)
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    for (const [cap, on] of [[gl.DEPTH_TEST, depth], [gl.CULL_FACE, cull], [gl.BLEND, blend]] as const) { if (on) gl.enable(cap); else gl.disable(cap) }
    gl.depthMask(write)
    gl.depthFunc(depthFunc)
    gl.blendFuncSeparate(blendFactors[0]!, blendFactors[1]!, blendFactors[2]!, blendFactors[3]!)
    gl.activeTexture(activeTexture)
  }
}
