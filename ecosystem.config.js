module.exports = {
  apps : [{
    name   : "horus-flow-api",
    script : "uvicorn",
    args   : "app.main:app --host 0.0.0.0 --port 8011",
    interpreter: "python3",
    watch  : false,
    autorestart: true,
    max_memory_restart: '1G',
    env: {
      "NODE_ENV": "production",
      "PORT": "8011"
      // API keys live only in /root/horus_flow_api/.env (FLOW_API_KEY_<n> / FLOW_API_TIER_<n>)
    }
  },
  {
    name   : "horus-flow-mcp",
    script : "horus_mcp.py",
    args   : "--transport sse --port 8012",
    interpreter: "/root/horus_flow_api/mcp_env/bin/python3",
    cwd    : "/root/horus_flow_api",
    watch  : false,
    autorestart: true,
    env: {
      "NODE_ENV": "production"
    }
  }]
}
