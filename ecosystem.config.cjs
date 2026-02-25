/**
 * PM2 ecosystem config for AgenticWorkflow.
 * Backend (8008): run with conda env model_zxw.
 * Usage:
 *   pm2 start ecosystem.config.cjs --only agentic-backend
 *   pm2 restart ecosystem.config.cjs --only agentic-backend
 */
const path = require("path");
// model_zxw 环境 Python；可通过环境变量覆盖: MODEL_ZXW_PYTHON=/path/to/python
const modelZxwPython = process.env.MODEL_ZXW_PYTHON || "/home/ubuntu/miniconda3/envs/model_zxw/bin/python";

module.exports = {
  apps: [
    {
      name: "agentic-backend",
      cwd: __dirname,
      script: "server.py",
      interpreter: modelZxwPython,
      args: "--host 0.0.0.0 --port 8008",
      exec_mode: "fork",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      error_file: path.join(__dirname, "backend.log"),
      out_file: path.join(__dirname, "backend.log"),
      merge_logs: true,
      time: true,
    },
  ],
};
