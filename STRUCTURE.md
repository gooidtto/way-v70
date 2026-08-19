# Project Structure

```text
.
├── config/        Xray templates
├── scripts/
│   ├── start.sh   runtime supervisor
│   ├── guard.sh   startup validation
│   ├── gateway.py gateway/router
│   └── generate.py runtime config/subscription generator
├── site/          public dashboard
├── Dockerfile
├── railway.toml
└── README.md
```

Runtime-generated state belongs in `/data` and is not committed.
