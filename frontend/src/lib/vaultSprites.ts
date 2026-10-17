// Camera-facing sprites for the 3D vault map. Cards are drawn on a 2D canvas (same look
// as a flat mind map) and used as textures, so the map reads as 2D head-on and the depth only
// shows when you rotate it. three-forcegraph disposes replaced objects (and their textures),
// so sprites are rebuilt freely when selection or theme changes.
import { CanvasTexture, SRGBColorSpace, Sprite, SpriteMaterial } from 'three'
import type { Palette } from './colors'

export const CARD_W = 150
export const CARD_H = 34
const PX = 4 // canvas pixels per world unit, keeps text crisp when zoomed in
const FONT = 'ui-sans-serif, -apple-system, system-ui, sans-serif'

function truncateToWidth(ctx: CanvasRenderingContext2D, text: string, max: number) {
  if (ctx.measureText(text).width <= max) return text
  let s = text
  while (s.length > 1 && ctx.measureText(`${s}…`).width > max) s = s.slice(0, -1)
  return `${s}…`
}

// `accent` tints the stripe and, faintly, the border.
function drawCard(ctx: CanvasRenderingContext2D, label: string, sub: string, p: Palette, accent: string, selected: boolean) {
  ctx.beginPath()
  ctx.roundRect(1, 1, CARD_W - 2, CARD_H - 2, 7)
  ctx.fillStyle = p.elev
  ctx.fill()
  ctx.lineWidth = selected ? 1.6 : 1
  ctx.strokeStyle = selected ? p.fg : accent
  ctx.globalAlpha = selected ? 1 : 0.45
  ctx.stroke()
  ctx.globalAlpha = 1

  ctx.fillStyle = accent
  ctx.beginPath()
  ctx.roundRect(8, 8, 3, CARD_H - 16, 1.5)
  ctx.fill()

  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = p.fg
  ctx.font = `500 8px ${FONT}`
  ctx.fillText(truncateToWidth(ctx, label, CARD_W - 28), 17, 15)
  ctx.fillStyle = p.muted
  ctx.font = `6.5px ${FONT}`
  ctx.fillText(truncateToWidth(ctx, sub, CARD_W - 28), 17, 26)
}

// `sub` is the small grey second line; `accent` the stripe colour (owner or branch).
export function makeCardSprite(label: string, sub: string, palette: Palette, accent: string, selected: boolean): Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = CARD_W * PX
  canvas.height = CARD_H * PX
  const ctx = canvas.getContext('2d')!
  ctx.scale(PX, PX)
  drawCard(ctx, label, sub, palette, accent, selected)

  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  // No depth test + a later render order: cards always paint over links, so edges never run
  // across the text (three-forcegraph gives links renderOrder 10, so cards must be above that).
  // Cards still sort back-to-front among themselves (three sorts transparent objects by
  // distance), and the selected card is lifted above the rest.
  const sprite = new Sprite(
    new SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false }),
  )
  sprite.renderOrder = selected ? 21 : 20
  sprite.scale.set(CARD_W, CARD_H, 1)
  return sprite
}
