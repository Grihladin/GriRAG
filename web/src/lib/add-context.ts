import { createContext, useContext } from 'react'

// Opens the Add dialog from anywhere, optionally with files already chosen (AppShell provides it).
export const AddContext = createContext<(files?: File[]) => void>(() => {})
export const useOpenAdd = () => useContext(AddContext)
