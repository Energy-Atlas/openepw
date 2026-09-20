import { useState } from 'react'
/** Keep separators editable; commit parsed values on blur before an action click. */
export function ListInput({
  value,
  onCommit,
  placeholder,
}: {
  value: string
  onCommit: (value: string) => void
  placeholder?: string
}) {
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <input
      value={editing ?? value}
      placeholder={placeholder}
      onChange={(e) => setEditing(e.target.value)}
      onBlur={() => {
        if (editing !== null) onCommit(editing)
        setEditing(null)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
      }}
    />
  )
}
