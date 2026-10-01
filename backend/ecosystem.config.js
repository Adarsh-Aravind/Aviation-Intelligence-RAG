// PM2 process file — runs the API and this project's own Cloudflare Tunnel (no Docker, no sudo).
//   pm2 start ecosystem.config.js && pm2 save
//
// Only ever manage these apps by name (aviation-rag-api, aviation-rag-tunnel) — any other PM2 apps
// on the host are left alone. `pm2 save` + PM2's boot service restore both after a power cut.
// The API listens on 127.0.0.1 only; the tunnel is the only way in.

const PORT = process.env.RAG_PORT || "8100";

// Home server: survive power cuts / Wi-Fi drops. Both processes retry the network themselves;
// PM2 restarts them if they ever exit, with exponential backoff and no restart cap.
const resilient = {
  autorestart: true,
  exp_backoff_restart_delay: 2000,
  max_restarts: 1000000,
  min_uptime: "20s",
  time: true,
  merge_logs: true,
};

module.exports = {
  apps: [
    {
      name: "aviation-rag-api",
      cwd: __dirname,
      script: ".venv/bin/uvicorn",
      // ONE worker on purpose: each worker would load its own copy of the embedding model.
      // The embedding model is loaded inside this process at startup (from the local cache).
      args: `app.main:app --host 127.0.0.1 --port ${PORT} --workers 1 --no-server-header --no-access-log`,
      interpreter: "none",
      env: {
        ENVIRONMENT: "production",
        PYTHONUNBUFFERED: "1",
        LOG_FILE: "logs/app.log", // app logs rotate in-process (5 MB x 3) — PM2 never trims its own files
        MALLOC_ARENA_MAX: "2", // limit glibc per-thread arenas (fragmentation) on Linux
      },
      ...resilient,
      max_memory_restart: "1200M", // normal usage is ~0.4 GB; restart if something leaks
      kill_timeout: 10000, // let the ingestion worker finish its current batch
      // Only uvicorn startup lines and crash tracebacks land here (app logs go to logs/app.log).
      out_file: "logs/api.out.log",
      error_file: "logs/api.err.log",
    },
    {
      name: "aviation-rag-tunnel",
      cwd: __dirname,
      script: "cloudflared",
      args: "tunnel --no-autoupdate --loglevel warn --config ../deploy/cloudflared/config.yml run",
      interpreter: "none",
      ...resilient,
      max_memory_restart: "200M",
      out_file: "logs/tunnel.out.log",
      error_file: "logs/tunnel.err.log",
    },
  ],
};
