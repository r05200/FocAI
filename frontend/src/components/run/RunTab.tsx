import StartRunForm from './StartRunForm'

// Landing state of the Research tab. Once runs are wired up this will swap to the live
// React Flow tree (TreeCanvas).
export default function RunTab() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 py-6">
      <h1 className="mb-7 text-center text-[28px] font-semibold">What should we research?</h1>
      <StartRunForm />
      <p className="mt-3 text-center text-xs text-muted">
        Describe the question you want researched.
      </p>
    </div>
  )
}
