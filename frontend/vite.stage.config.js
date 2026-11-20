// Build config for the public /stage demo. It is a separate mini-app: the real screens are reused as they are,
// but every import of src/services/api.js is swapped for stage/demoApi.js (in-memory dummy data, no network).
// Output goes to dist/stage, next to the real app's files.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const here = path.dirname(fileURLToPath(import.meta.url));
const norm = (p) => path.normalize(p).toLowerCase();
const realApi = norm(path.resolve(here, 'src/services/api.js'));
const demoApi = path.resolve(here, 'stage/demoApi.js');

function swapApiForDemo() {
  return {
    name: 'stage-swap-api-for-demo',
    enforce: 'pre',
    async resolveId(source, importer, options) {
      if (!importer || !/(^|\/)services\/api(\.js)?$/.test(source)) return null;
      const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
      return resolved && norm(resolved.id) === realApi ? demoApi : null;
    },
  };
}

export default defineConfig({
  root: path.resolve(here, 'stage'),
  base: '/stage/',
  publicDir: false,
  cacheDir: path.resolve(here, 'node_modules/.vite-stage'), // separate from the main app's dependency cache
  plugins: [swapApiForDemo(), react(), tailwindcss()],
  server: { fs: { allow: [here] } },
  build: { outDir: path.resolve(here, 'dist/stage'), emptyOutDir: true },
});
