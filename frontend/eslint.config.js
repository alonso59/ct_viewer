import js from '@eslint/js'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', '.vite', 'node_modules', 'playwright-report', 'test-results', 'src/api/schema.d.ts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-explicit-any': 'error', // FE-01
      // FE-11: all UI text goes through t(); no literal JSX strings.
      'react/jsx-no-literals': ['error', { noStrings: true, ignoreProps: true }],
    },
  },
  { files: ['**/*.test.{ts,tsx}', 'e2e/**'], rules: { 'react/jsx-no-literals': 'off' } },
)
