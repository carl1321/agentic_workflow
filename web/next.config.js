/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import "./src/env.js";
import createNextIntlPlugin from 'next-intl/plugin';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const withNextIntl = createNextIntlPlugin('./src/i18n.ts');

/** @type {import("next").NextConfig} */

// DeerFlow leverages **Turbopack** during development for faster builds and a smoother developer experience.
// However, in production, **Webpack** is used instead.
//
// This decision is based on the current recommendation to avoid using Turbopack for critical projects, as it
// is still evolving and may not yet be fully stable for production environments.

const config = {
  // For development mode
  turbopack: {
    rules: {
      "*.md": {
        loaders: ["raw-loader"],
        as: "*.js",
      },
    },
  },

  // For production mode
  webpack: (config) => {
    config.module.rules.push({
      test: /\.md$/,
      use: "raw-loader",
    });
    
    // Add path aliases for @
    config.resolve.alias['@'] = path.resolve(__dirname, 'src/components/workflow/workflow');
    config.resolve.alias['@/app'] = path.resolve(__dirname, 'src/components/workflow/workflow');
    config.resolve.alias['@/service'] = path.resolve(__dirname, 'src/components/workflow/workflow/service');
    config.resolve.alias['@/types'] = path.resolve(__dirname, 'src/components/workflow/workflow/types');
    config.resolve.alias['@/utils'] = path.resolve(__dirname, 'src/components/workflow/workflow/utils');
    config.resolve.alias['@/hooks'] = path.resolve(__dirname, 'src/hooks');
    config.resolve.alias['@/context'] = path.resolve(__dirname, 'src/components/workflow/workflow/context');
    config.resolve.alias['@/models'] = path.resolve(__dirname, 'src/components/workflow/workflow/models');
    
    return config;
  },

  // ... rest of the configuration.
  output: "standalone",
};

export default withNextIntl(config);
