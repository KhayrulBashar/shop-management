/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./app/templates/**/*.{html,js}",
    "./app/static/**/*.{html,js,css}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          bg: '#020617',
          card: '#0F172A',
          cardSub: '#1E293B',
          border: '#334155',
          cyan: '#22D3EE',
          cyanLight: '#67E8F9',
          indigo: '#6366F1',
          indigoDark: '#4F46E5',
          purpleAura: '#A855F7',
          success: '#10B981',
          warning: '#F59E0B',
          danger: '#F43F5E',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px -3px rgba(34, 211, 238, 0.35)',
        'glow-indigo': '0 0 25px -4px rgba(99, 102, 241, 0.35)',
        'glow-purple': '0 0 30px -5px rgba(168, 85, 247, 0.25)',
      }
    }
  },
  plugins: [],
}
