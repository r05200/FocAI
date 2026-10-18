// Smooth camera moves for the 3D vault map. three-render-objects' built-in tween eases poorly,
// so we drive the camera ourselves with a CSS-style cubic-bezier curve.

export interface Vec3 {
  x: number
  y: number
  z: number
}

// Same maths as CSS cubic-bezier(x1, y1, x2, y2): solve x(t) = progress with Newton's method,
// then return y(t).
function cubicBezier(x1: number, y1: number, x2: number, y2: number) {
  const bez = (a: number, b: number, t: number) => 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t ** 2 + t ** 3
  const slope = (a: number, b: number, t: number) =>
    3 * a * (1 - t) ** 2 + 6 * (b - a) * (1 - t) * t + 3 * (1 - b) * t ** 2
  return (x: number) => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let t = x
    for (let i = 0; i < 8; i++) {
      const err = bez(x1, x2, t) - x
      const d = slope(x1, x2, t)
      if (Math.abs(err) < 1e-5 || d === 0) break
      t -= err / d
    }
    return bez(y1, y2, Math.min(Math.max(t, 0), 1))
  }
}

// Gentle start and a long, soft landing.
const EASE_IN_OUT = cubicBezier(0.65, 0, 0.35, 1)
// Fast out of the gate, settles slowly: good for the fly-in.
export const EASE_OUT = cubicBezier(0.22, 1, 0.36, 1)

const lerp = (a: number, b: number, k: number) => a + (b - a) * k

export interface Flight {
  cancel: () => void
}

// Animate the camera from where it is now to `to`, looking at `lookAt`. `apply` is
// ForceGraph's cameraPosition(pos, lookAt, 0). Returns a handle so a newer move or user input
// can cancel it.
export function flyCamera(
  from: { pos: Vec3; look: Vec3 },
  to: { pos: Vec3; look: Vec3 },
  ms: number,
  apply: (pos: Vec3, look: Vec3) => void,
  ease: (x: number) => number = EASE_IN_OUT,
): Flight {
  let frame = 0
  const start = performance.now()
  const step = (now: number) => {
    const k = ease(Math.min(1, (now - start) / ms))
    apply(
      { x: lerp(from.pos.x, to.pos.x, k), y: lerp(from.pos.y, to.pos.y, k), z: lerp(from.pos.z, to.pos.z, k) },
      { x: lerp(from.look.x, to.look.x, k), y: lerp(from.look.y, to.look.y, k), z: lerp(from.look.z, to.look.z, k) },
    )
    if (now - start < ms) frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
  return { cancel: () => cancelAnimationFrame(frame) }
}
