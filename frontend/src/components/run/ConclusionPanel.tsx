import type { TreeNode } from '../../types'
import { CloseIcon } from '../ui/Icons'

interface Props {
  open: boolean
  node: TreeNode | null // the conclusion node
  onClose: () => void
}

// Right-hand sidebar (same slot and look as the logs) with the run's conclusion: the answer the
// agent reached, taken from the conclusion node.
export default function ConclusionPanel({ open, node, onClose }: Props) {
  const answer = node?.result?.trim()
  return (
    <aside
      aria-label="Conclusion"
      aria-hidden={!open}
      inert={!open}
      // A flex sibling of the tree: opening it narrows the tree rather than covering it (and the
      // node's card with it).
      className={`shrink-0 overflow-hidden border-line bg-sidebar transition-[width] duration-300 ease-zoom ${
        open ? 'w-100 border-l' : 'w-0'
      }`}
    >
      <div className="flex h-full w-100 flex-col">
      <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
        <div className="min-w-0">
          <h2 className="font-semibold">Conclusion</h2>
          <p className="text-xs text-muted">The answer the run reached</p>
        </div>
        <button
          aria-label="Close conclusion"
          onClick={onClose}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <CloseIcon />
        </button>
      </header>
      <div className="flex-1 overflow-auto px-4 pb-4">
        {answer ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{answer}</p>
        ) : (
          <p className="py-6 text-center text-sm text-muted">The conclusion hasn’t been written yet.</p>
        )}
      </div>
      </div>
    </aside>
  )
}
