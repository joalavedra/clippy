# Clippy service layer

Run the API and its worker with:

```bash
CLIPPY_DATA_DIR=./data uvicorn service.app:app --port 8100
```

Create a local project:

```bash
curl -X POST http://localhost:8100/api/projects \
  -H 'content-type: application/json' \
  -d '{"name":"demo","platform":"local","local_path":"/path/video.mp4"}'
```

Create a job using the returned project ID:

```bash
curl -X POST http://localhost:8100/api/jobs \
  -H 'content-type: application/json' \
  -d '{"project_ids":["PROJECT_ID"],"brief":"A concise highlight","formats":[{"ratio":"9:16","min":8,"max":12}]}'
```

Inspect jobs and assets:

```bash
curl http://localhost:8100/api/jobs
curl http://localhost:8100/api/assets
```
