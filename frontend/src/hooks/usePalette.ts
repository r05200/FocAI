import { useEffect, useState } from 'react'
import { readPalette, type Palette } from '../lib/colors'

// Canvas and WebGL sprites can't follow CSS variables, so re-read the palette when the OS theme flips.
export function usePalette(): Palette {
  const [palette, setPalette] = useState<Palette>(readPalette)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = () => setPalette(readPalette())
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return palette
}
