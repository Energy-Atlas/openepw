import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/geist'
import { App } from './app/App'
import '../src/shell/shell.css'
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
