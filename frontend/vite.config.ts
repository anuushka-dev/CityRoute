import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const BACKEND_ORIGIN = 'http://127.0.0.1:8001';
const FRONTEND_HOST = 'localhost';
const FRONTEND_PORT = 5173;
const API_PREFIX = '/api';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: FRONTEND_HOST,
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      [API_PREFIX]: {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
    },
  },
});
