# Sample Pipe

This sample uses the README's complex localization pipeline and runs in long-lived watch mode.

## Run with Docker Compose

```bash
docker compose up --build
```

The watcher compiles the pipeline and then polls for ready bundles in `/inbox`.

Host mounts:
- `./artifacts -> /artifacts`
- `./inbox -> /inbox`
- `./ -> /workspace`

## Inbox bundle format

Drop bundles in:

```text
inbox/localization-release/<bundle_id>/
```

Required:
- `manifest.json`
- `payload/`
- `_READY`

Optional:
- `run_config.json`
- `trigger.json`

Run IDs are generated as:

```text
<pipeline_id>_<unix_timestamp>_<payload_hash>
```
