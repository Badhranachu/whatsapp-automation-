import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { createServer, defineConfig } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))

// Dev only: serve the public /stage demo (see vite.stage.config.js) from this same dev server, so
// http://localhost:5173/stage works while developing. It does nothing in a production build.
function stageDemoInDev() {
  return {
    name: 'stage-demo-in-dev',
    apply: 'serve',
    async configureServer(server) {
      const stage = await createServer({
        configFile: path.resolve(here, 'vite.stage.config.js'),
        cacheDir: path.resolve(here, 'node_modules/.vite-stage'),
        server: { middlewareMode: true, hmr: false },
        appType: 'spa',
      })
      server.httpServer?.once('close', () => stage.close())
      server.middlewares.use((req, res, next) => {
        const url = req.url || ''
        if (url === '/stage') {
          res.statusCode = 302
          res.setHeader('Location', '/stage/')
          res.end()
        } else if (url.startsWith('/stage/')) {
          stage.middlewares(req, res, next)
        } else {
          next()
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), stageDemoInDev()],
})
