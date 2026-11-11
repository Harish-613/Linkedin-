// Content scripts can't be ES modules, so this builds one self-contained IIFE.
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    lib: { entry: 'src/content/index.tsx', name: 'LinkedInPP', formats: ['iife'], fileName: () => 'content.js' },
  },
});
