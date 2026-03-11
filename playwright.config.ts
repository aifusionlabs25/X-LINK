import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: './tests',
    fullyParallel: true,
    retries: 1,
    // Workers disabled for CDP to prevent socket collision, but available for CI run modes
    workers: process.env.CI ? 2 : 1,
    reporter: 'html',
    use: {
        baseURL: 'http://localhost:3000',
        trace: 'on-first-retry',
        headless: false, // Must be false for BitWarden and CDP testing
    },
    projects: [
        { name: 'chromium', use: { browserName: 'chromium' } },
    ],
});
