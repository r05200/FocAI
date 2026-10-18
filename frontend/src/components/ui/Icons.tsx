// Placeholder icons (simple inline SVGs). Swap for a real icon set later.
import type { SVGProps } from 'react'

function Svg(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={20}
      height={20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  )
}

export function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
    </Svg>
  )
}

export function VaultIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="2.5" />
      <circle cx="5" cy="5" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M10.2 10.2 6.4 6.4M13.9 10.8l3.4-3.4M10.3 13.8l-2.9 3.7M13.9 13.4l3.6 3.2" />
    </Svg>
  )
}

export function SettingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </Svg>
  )
}

export function FolderIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={18} height={18} {...props}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    </Svg>
  )
}

export function ArrowRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg strokeWidth={2.2} {...props}>
      <path d="M5 12h14M12 5l7 7-7 7" />
    </Svg>
  )
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} strokeWidth={2.2} {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  )
}

export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} strokeWidth={2.2} {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  )
}

export function MinusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} strokeWidth={2.2} {...props}>
      <path d="M5 12h14" />
    </Svg>
  )
}

export function FitIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
    </Svg>
  )
}

export function CursorIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M5 3l14 7-6 2-2 6-6-15Z" />
    </Svg>
  )
}

export function HandIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11.5v-7a1.5 1.5 0 0 1 3 0V12M14 6.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1a6 6 0 0 1-4.6-2.2L3 15.5a1.6 1.6 0 0 1 2.4-2L8 15.5" />
    </Svg>
  )
}

export function TargetIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="2" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </Svg>
  )
}

export function DirectiveIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={18} height={18} {...props}>
      <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
    </Svg>
  )
}

export function ChevronDownIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} strokeWidth={2.2} {...props}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  )
}

export function HistoryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </Svg>
  )
}

export function StopIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} fill="currentColor" stroke="none" {...props}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
    </Svg>
  )
}

export function IdeasIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" />
    </Svg>
  )
}

export function BellIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </Svg>
  )
}

export function FileIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </Svg>
  )
}

export function ImageIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.6" />
      <path d="m21 16-5-5-9 9" />
    </Svg>
  )
}

export function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} strokeWidth={2.4} {...props}>
      <path d="m5 12 5 5 9-10" />
    </Svg>
  )
}

// A vault (hub with satellites) with a small plus: "add a vault", distinct from the plain + that
// adds knowledge to the current one.
export function MoveIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M12 3v18M3 12h18M12 3 9 6M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" />
    </Svg>
  )
}

// Rotating arrow around a small cube-ish square: "put the view back the way it was".
export function ResetViewIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </Svg>
  )
}

export function ArrowLeftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} strokeWidth={2.2} {...props}>
      <path d="M19 12H5M12 19l-7-7 7-7" />
    </Svg>
  )
}

export function LayoutIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={16} height={16} {...props}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 17.5h7M17.5 14v7" />
    </Svg>
  )
}

export function PauseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} fill="currentColor" stroke="none" {...props}>
      <rect x="5" y="4" width="4.5" height="16" rx="1.2" />
      <rect x="14.5" y="4" width="4.5" height="16" rx="1.2" />
    </Svg>
  )
}

export function PlayIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg width={14} height={14} fill="currentColor" stroke="none" {...props}>
      <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />
    </Svg>
  )
}
