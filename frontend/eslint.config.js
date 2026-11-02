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
      '@typescript-eslint/no-explicit-any': 'error',
      // All UI text goes through t().
      'react/jsx-no-literals': ['error', { noStrings: true, ignoreProps: true }],
      // An effect returns nothing or its cleanup: an expression body leaks the callee's value
      // (e.g. a Promise from scrollIntoView), which React then calls as a cleanup
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name=/^use(Layout)?Effect$/] > ArrowFunctionExpression.arguments:first-child[body.type!='BlockStatement'][body.type!='ArrowFunctionExpression']",
          message: 'Use a block body: an effect must return nothing or a cleanup function.',
        },
      ],
    },
  },
  { files: ['**/*.test.{ts,tsx}', 'e2e/**'], rules: { 'react/jsx-no-literals': 'off' } },
)
