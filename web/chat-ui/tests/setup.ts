import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)

// Parallel test files can slow first renders; allow async queries more than the 1 s default.
configure({ asyncUtilTimeout: 3000 })
