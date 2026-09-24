// 2D slice renderer for NiiVue's custom-slice-shader hook (VW-03/05/07, NFR-02).
//
// NiiVue windows a volume by re-uploading and re-compositing the whole 3D texture (≈ 0.5 s for a
// 512×512×600 CT). Here the full-resolution image and label volumes are uploaded ONCE; window,
// level, label colours, per-label opacity and outline are shader inputs, so a W/L drag only
// changes uniforms. NiiVue still owns layout, pan/zoom, picking and the 3D tile.

/** Texture units NiiVue does not use (it stays below 10) */
const UNIT = { image: 12, label: 13, lut: 14 } as const

export const SLICE_FRAG = `#version 300 es
precision highp int;
precision highp float;
precision highp sampler3D;
precision highp usampler3D;
uniform int axCorSag;
uniform sampler3D rwImage;
uniform usampler3D rwLabel;
uniform sampler2D rwLut;
uniform mat4 rwImgMtx;
uniform mat4 rwLabMtx;
uniform vec2 rwScale;
uniform vec2 rwRange;
uniform float rwOverlay;
uniform int rwHasLabel;
uniform vec3 rwStep;
uniform int rwInvert;
uniform int rwSlabMode;
uniform vec3 rwSlabHalf;
in vec3 texPos;
out vec4 color;

uint labelAt(vec3 p) {
  vec3 t = (rwLabMtx * vec4(p, 1.0)).xyz;
  if (any(lessThan(t, vec3(0.0))) || any(greaterThanEqual(t, vec3(1.0)))) return 0u;
  ivec3 d = textureSize(rwLabel, 0);
  return texelFetch(rwLabel, clamp(ivec3(t * vec3(d)), ivec3(0), d - 1), 0).r;
}

float imageAt(vec3 p) {
  vec3 t = (rwImgMtx * vec4(p, 1.0)).xyz;
  return texture(rwImage, t).r * rwScale.x + rwScale.y;
}

void main(void) {
  float v = imageAt(texPos);
  // VW-23 slab: max / min / mean along the plane normal over ± half the thickness
  if (rwSlabMode > 0) {
    vec3 dir = axCorSag == 0 ? vec3(0.0, 0.0, 1.0) : (axCorSag == 1 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0));
    float st = max(dot(dir, rwStep), 1e-6);
    int n = int(min(64.0, floor(dot(dir, rwSlabHalf) / st)));
    float acc = v;
    float lo = v;
    float hi = v;
    float cnt = 1.0;
    for (int k = 1; k <= 64; k++) {
      if (k > n) break;
      for (int s = -1; s <= 1; s += 2) {
        vec3 p = texPos + dir * (float(k) * st * float(s));
        if (any(lessThan(p, vec3(0.0))) || any(greaterThan(p, vec3(1.0)))) continue;
        float w = imageAt(p);
        acc += w;
        lo = min(lo, w);
        hi = max(hi, w);
        cnt += 1.0;
      }
    }
    v = rwSlabMode == 1 ? hi : (rwSlabMode == 2 ? lo : acc / cnt);
  }
  float g = clamp((v - rwRange.x) / max(1e-6, rwRange.y - rwRange.x), 0.0, 1.0);
  if (rwInvert == 1) g = 1.0 - g;
  color = vec4(g, g, g, 1.0);
  if (rwHasLabel == 0 || rwOverlay <= 0.0) return;
  uint idx = labelAt(texPos);
  if (idx == 0u) return;
  int w = textureSize(rwLut, 0).x;
  ivec2 at = ivec2(min(int(idx), w - 1), 0);
  vec4 c = texelFetch(rwLut, at, 0);
  bool outline = texelFetch(rwLut, ivec2(at.x, 1), 0).r > 0.5;
  // In-plane 4-neighbourhood, like 3D Slicer's outline mode
  vec3 a = axCorSag == 2 ? vec3(0.0, rwStep.y, 0.0) : vec3(rwStep.x, 0.0, 0.0);
  vec3 b = axCorSag == 0 ? vec3(0.0, rwStep.y, 0.0) : vec3(0.0, 0.0, rwStep.z);
  bool edge = labelAt(texPos + a) != idx || labelAt(texPos - a) != idx || labelAt(texPos + b) != idx || labelAt(texPos - b) != idx;
  float alpha = c.a;
  if (outline) alpha = edge ? max(0.8, c.a) : 0.0;
  color.rgb = mix(color.rgb, c.rgb, alpha * rwOverlay);
}
`

type Typed = Int8Array | Uint8Array | Int16Array | Uint16Array | Int32Array | Uint32Array | Float32Array | Float64Array

const R16_EXT = 0x822a
const R16_SNORM_EXT = 0x8f98

export interface ImageSource {
  data: Typed
  dims: [number, number, number]
  slope: number
  inter: number
}

/** Column-major 4×4 */
export type Mat4 = Float32Array

export class SliceRenderer {
  private image: WebGLTexture | null = null
  private label: WebGLTexture | null = null
  private lut: WebGLTexture | null = null
  private scale: [number, number] = [1, 0]
  private range: [number, number] = [0, 1]
  private overlay = 1
  private imgMtx: Mat4 = new Float32Array(16)
  private labMtx: Mat4 = new Float32Array(16)
  private step: [number, number, number] = [0, 0, 0]
  private invert = false
  private slab: { mode: number; half: [number, number, number] } = { mode: 0, half: [0, 0, 0] }
  private linear = true
  hasLabel = false

  constructor(private gl: WebGL2RenderingContext) {}

  /** Uploads the image once. Signed 16-bit CT uses R16_SNORM (filterable, no copy) when available. */
  setImage(src: ImageSource) {
    const gl = this.gl
    this.drop('image')
    const tex = gl.createTexture()
    gl.activeTexture(gl.TEXTURE0 + UNIT.image)
    gl.bindTexture(gl.TEXTURE_3D, tex)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
    const [nx, ny, nz] = src.dims
    const norm16 = !!gl.getExtension('EXT_texture_norm16')
    const floatLinear = !!gl.getExtension('OES_texture_float_linear')
    let filter: number = gl.LINEAR
    let k = 1
    const d = src.data
    if (d instanceof Uint8Array) {
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, nx, ny, nz, 0, gl.RED, gl.UNSIGNED_BYTE, d)
      k = 255
    } else if (d instanceof Int8Array) {
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8_SNORM, nx, ny, nz, 0, gl.RED, gl.BYTE, d)
      k = 127
    } else if (d instanceof Int16Array && norm16) {
      gl.texImage3D(gl.TEXTURE_3D, 0, R16_SNORM_EXT, nx, ny, nz, 0, gl.RED, gl.SHORT, d)
      k = 32767
    } else if (d instanceof Uint16Array && norm16) {
      gl.texImage3D(gl.TEXTURE_3D, 0, R16_EXT, nx, ny, nz, 0, gl.RED, gl.UNSIGNED_SHORT, d)
      k = 65535
    } else {
      // Fallback: 32-bit float (4 bytes/voxel), linear only with OES_texture_float_linear
      const f = d instanceof Float32Array ? d : Float32Array.from(d as ArrayLike<number>)
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.R32F, nx, ny, nz, 0, gl.RED, gl.FLOAT, f)
      if (!floatLinear) filter = gl.NEAREST
    }
    this.filterable = filter === gl.LINEAR
    const f = this.linear && this.filterable ? gl.LINEAR : gl.NEAREST
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, f)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, f)
    for (const w of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(gl.TEXTURE_3D, w, gl.CLAMP_TO_EDGE)
    this.image = tex
    // stored value × k = raw; raw × slope + inter = physical value
    this.scale = [k * src.slope, src.inter]
  }

  /** Label volume as an integer texture (exact indices, never interpolated) */
  setLabel(data: Uint8Array | Uint16Array | null, dims: [number, number, number]) {
    const gl = this.gl
    this.drop('label')
    this.hasLabel = !!data
    if (!data) return
    const tex = gl.createTexture()
    gl.activeTexture(gl.TEXTURE0 + UNIT.label)
    gl.bindTexture(gl.TEXTURE_3D, tex)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
    const [nx, ny, nz] = dims
    if (data instanceof Uint8Array) gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8UI, nx, ny, nz, 0, gl.RED_INTEGER, gl.UNSIGNED_BYTE, data)
    else gl.texImage3D(gl.TEXTURE_3D, 0, gl.R16UI, nx, ny, nz, 0, gl.RED_INTEGER, gl.UNSIGNED_SHORT, data)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    this.label = tex
  }

  /** 2-row LUT: row 0 = RGBA fill (A = opacity, 0 = hidden), row 1 R = outline flag */
  setLut(rows: Uint8Array, width: number) {
    const gl = this.gl
    if (!this.lut) this.lut = gl.createTexture()
    gl.activeTexture(gl.TEXTURE0 + UNIT.lut)
    gl.bindTexture(gl.TEXTURE_2D, this.lut)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, rows)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
  }

  setWindow(lo: number, hi: number) {
    this.range = [lo, hi]
  }

  setOverlay(opacity: number) {
    this.overlay = opacity
  }

  private filterable = true

  /** VW-25: linear or nearest-neighbour sampling of the image (labels are always exact) */
  setInterpolation(linear: boolean) {
    this.linear = linear
    if (!this.image) return
    const gl = this.gl
    const f = linear && this.filterable ? gl.LINEAR : gl.NEAREST
    gl.activeTexture(gl.TEXTURE0 + UNIT.image)
    gl.bindTexture(gl.TEXTURE_3D, this.image)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, f)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, f)
    gl.activeTexture(gl.TEXTURE0)
  }

  setInvert(on: boolean) {
    this.invert = on
  }

  /** VW-23: `mode` 0 none, 1 MIP, 2 MinIP, 3 mean; `half` = half thickness in texPos fraction */
  setSlab(mode: number, half: [number, number, number]) {
    this.slab = { mode, half }
  }

  /** Maps from NiiVue's RAS texture fraction (texPos) to each volume's native texture coords */
  setMatrices(img: Mat4, lab: Mat4 | null, step: [number, number, number]) {
    this.imgMtx = img
    if (lab) this.labMtx = lab
    this.step = step
  }

  /** Bind textures and push uniforms into the slice program just before NiiVue draws a tile */
  prepare(program: WebGLProgram) {
    const gl = this.gl
    if (!this.image) return
    gl.activeTexture(gl.TEXTURE0 + UNIT.image)
    gl.bindTexture(gl.TEXTURE_3D, this.image)
    gl.activeTexture(gl.TEXTURE0 + UNIT.label)
    gl.bindTexture(gl.TEXTURE_3D, this.label)
    gl.activeTexture(gl.TEXTURE0 + UNIT.lut)
    gl.bindTexture(gl.TEXTURE_2D, this.lut)
    gl.activeTexture(gl.TEXTURE0)
    const prev = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram | null
    gl.useProgram(program)
    const u = (n: string) => gl.getUniformLocation(program, n)
    gl.uniform1i(u('rwImage'), UNIT.image)
    gl.uniform1i(u('rwLabel'), UNIT.label)
    gl.uniform1i(u('rwLut'), UNIT.lut)
    gl.uniformMatrix4fv(u('rwImgMtx'), false, this.imgMtx)
    gl.uniformMatrix4fv(u('rwLabMtx'), false, this.labMtx)
    gl.uniform2f(u('rwScale'), this.scale[0], this.scale[1])
    gl.uniform2f(u('rwRange'), this.range[0], this.range[1])
    gl.uniform1f(u('rwOverlay'), this.overlay)
    gl.uniform1i(u('rwHasLabel'), this.hasLabel && this.label && this.lut ? 1 : 0)
    gl.uniform3f(u('rwStep'), ...this.step)
    gl.uniform1i(u('rwInvert'), this.invert ? 1 : 0)
    gl.uniform1i(u('rwSlabMode'), this.slab.mode)
    gl.uniform3f(u('rwSlabHalf'), ...this.slab.half)
    gl.useProgram(prev)
  }

  private drop(which: 'image' | 'label') {
    const t = this[which]
    if (t) this.gl.deleteTexture(t)
    this[which] = null
  }

  dispose() {
    this.drop('image')
    this.drop('label')
    if (this.lut) this.gl.deleteTexture(this.lut)
    this.lut = null
  }
}
