/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        neutral: {
          bg: 'var(--color-bg)',
          surface: 'var(--color-surface)',
          elevated: 'var(--color-elevated)',
          sunken: 'var(--color-sunken)',
          border: 'var(--color-border)',
          'border-strong': 'var(--color-border-strong)',
          'border-subtle': 'var(--color-border-subtle)',
          'text-primary': 'var(--color-text-primary)',
          'text-secondary': 'var(--color-text-secondary)',
          'text-muted': 'var(--color-text-muted)',
          'fill-primary': 'var(--color-fill-primary)',
          'fill-secondary': 'var(--color-fill-secondary)',
        },
      },
    },
  },
  plugins: [],
}
