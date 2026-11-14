import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './integration', outputDir: './integration-results', workers: 1,
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  webServer: [
    { command: `${process.env.E2E_PYTHON || 'python3'} -m scripts.workspace_e2e`, cwd: '../backend', url: 'http://127.0.0.1:8011/health', reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5174', url: 'http://127.0.0.1:5174',
      env: { BACKEND_URL: 'http://127.0.0.1:8011', VITE_DEV_USER: '101' }, reuseExistingServer: false },
  ],
});
