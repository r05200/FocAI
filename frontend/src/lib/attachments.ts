// FIXME(attachments): NOT WIRED UP. The prompt bar's attach menu is disabled for now (see
// StartRunForm.tsx), so nothing imports this yet. It holds the checks (type, size, empty,
// duplicate, max count) to reuse once uploading is built. Open questions before enabling it:
//   - folders: browsers can't expose a folder's real path, and uploading its contents is
//     wasteful when the backend can read the disk; probably needs a backend folder-browse route;
//   - POST /api/runs doesn't accept attachments yet.

type AttachKind = 'file' | 'image' | 'folder'

interface Attachment {
  id: string
  kind: AttachKind
  name: string
  files: File[]
  bytes: number
}

const MB = 1024 * 1024

const LIMITS = {
  file: { maxBytes: 20 * MB },
  image: { maxBytes: 10 * MB },
  maxAttachments: 10,
}

// FLAG (ignore unless asked): accepts PDF/Word/etc., but backend ingest takes text only (PRD: no PDF parsing).
const DOC_EXTENSIONS = ['pdf', 'txt', 'md', 'markdown', 'doc', 'docx', 'csv', 'json', 'tex', 'html', 'rtf']
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']

// `accept` attribute for each picker (folders can't be filtered by the browser).
export const ACCEPT: Record<Exclude<AttachKind, 'folder'>, string> = {
  file: DOC_EXTENSIONS.map((e) => `.${e}`).join(','),
  image: 'image/*',
}

function ext(name: string) {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toLowerCase() : ''
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < MB) return `${Math.round(n / 1024)} KB`
  return `${(n / MB).toFixed(n < 10 * MB ? 1 : 0)} MB`
}

const isImage = (f: File) => f.type.startsWith('image/') || IMAGE_EXTENSIONS.includes(ext(f.name))
const isDoc = (f: File) => DOC_EXTENSIONS.includes(ext(f.name))

let counter = 0
const nextId = () => `att_${++counter}`

// Check files or images the user picked. Returns what was accepted plus one message per problem.
export function checkPicked(kind: Exclude<AttachKind, 'folder'>, picked: File[], existing: Attachment[]) {
  const accepted: Attachment[] = []
  const errors: string[] = []
  const already = new Set(existing.flatMap((a) => a.files.map((f) => f.name)))
  let room = LIMITS.maxAttachments - existing.length
  const { maxBytes } = LIMITS[kind]
  for (const f of picked) {
    if (already.has(f.name)) {
      errors.push(`“${f.name}” is already attached.`)
    } else if (kind === 'image' && !isImage(f)) {
      errors.push(`“${f.name}” isn't an image.`)
    } else if (kind === 'file' && !isDoc(f)) {
      errors.push(`“${f.name}” isn't a supported document (${DOC_EXTENSIONS.slice(0, 6).join(', ')}…).`)
    } else if (f.size === 0) {
      errors.push(`“${f.name}” is empty.`)
    } else if (f.size > maxBytes) {
      errors.push(`“${f.name}” is ${formatBytes(f.size)}; the limit is ${formatBytes(maxBytes)}.`)
    } else if (room <= 0) {
      errors.push(`You can attach up to ${LIMITS.maxAttachments} items.`)
      break
    } else {
      accepted.push({ id: nextId(), kind, name: f.name, files: [f], bytes: f.size })
      already.add(f.name)
      room--
    }
  }
  return { accepted, errors }
}
