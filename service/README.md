# Clippy service layer

Run the API and its worker with:

```bash
CLIPPY_API_KEY=dev-secret \
CLIPPY_LOCAL_MEDIA_ROOTS=./data/uploads \
CLIPPY_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173 \
CLIPPY_DATA_DIR=./data uvicorn service.app:app --port 8100
```

Create a local project:

```bash
curl -X POST http://localhost:8100/api/projects \
  -H 'X-API-Key: dev-secret' \
  -H 'content-type: application/json' \
  -d '{"name":"demo","platform":"local","local_path":"/path/video.mp4"}'
```

Create a job using the returned project ID:

```bash
curl -X POST http://localhost:8100/api/jobs \
  -H 'X-API-Key: dev-secret' \
  -H 'content-type: application/json' \
  -d '{"project_ids":["PROJECT_ID"],"brief":"A concise highlight","formats":[{"ratio":"9:16","min":8,"max":12}]}'
```

Inspect jobs and assets:

```bash
curl -H 'X-API-Key: dev-secret' http://localhost:8100/api/jobs
curl -H 'X-API-Key: dev-secret' http://localhost:8100/api/assets
```

`CLIPPY_API_KEY` protects every API route except `/api/health` and also protects
downloaded files. `CLIPPY_LOCAL_MEDIA_ROOTS` controls which local files can be
registered; it defaults to `./data/uploads`.
