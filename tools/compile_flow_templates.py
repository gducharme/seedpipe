from __future__ import annotations

_FLOW_RUNTIME_HELPERS = """
def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()

class RunManifestRepository:
    def __init__(self, path: Path):
        self.path = path

    def read_or_seed(self, run_id: str) -> dict[str, object]:
        if not self.path.exists():
            return self.seed(run_id)
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError('run manifest must be a JSON object')
        return payload

    def seed(self, run_id: str) -> dict[str, object]:
        stages = [
            {
                'stage_id': stage_id,
                'status': 'pending',
                'attempt': 0,
                'updated_at': now_rfc3339(),
            }
            for stage_id in STAGES
        ]
        payload = {
            'manifest_version': 'phase1-run-resume-v1',
            'pipeline_id': PIPELINE_ID,
            'run_id': run_id,
            'created_at': now_rfc3339(),
            'updated_at': now_rfc3339(),
            'failure_stage_id': None,
            'loop_iteration': 1,
            'artifact_index': {},
            'active_item_ids': [],
            'item_attempts': {},
            'stages': stages,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\\n')
        return payload

    def write(self, manifest: dict[str, object]) -> None:
        manifest['updated_at'] = now_rfc3339()
        self.path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\\n')

    @staticmethod
    def stage_rows(manifest: dict[str, object]) -> list[dict[str, object]]:
        rows = manifest.get('stages', [])
        if not isinstance(rows, list):
            raise ValueError('run manifest field stages must be an array')
        typed_rows = [row for row in rows if isinstance(row, dict)]
        if len(typed_rows) != len(rows):
            raise ValueError('run manifest stages entries must be objects')
        return typed_rows

_MANIFEST_REPO = RunManifestRepository(Path(RUN_MANIFEST_FILE))

def _read_manifest(run_id: str) -> dict[str, object]:
    return _MANIFEST_REPO.read_or_seed(run_id)

def _write_manifest(manifest: dict[str, object]) -> None:
    _MANIFEST_REPO.write(manifest)

def _task_paths(run_id: str, stage_id: str) -> tuple[Path, Path, Path]:
    run_root = Path('runs') / run_id
    tasks_dir = run_root / 'tasks'
    json_path = tasks_dir / f'{stage_id}.task.json'
    md_path = tasks_dir / f'{stage_id}.md'
    marker_path = run_root / f'WAITING_HUMAN.{stage_id}'
    return json_path, md_path, marker_path

def _render_task_packet_markdown(packet: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"# Task: {packet.get('stage_id', '')}")
    lines.append('')
    lines.append('## Purpose')
    lines.append(str(packet.get('purpose', '')))
    lines.append('')
    lines.append('## Required Inputs')
    for item in packet.get('required_inputs', []):
        lines.append(f"- {item}")
    lines.append('')
    lines.append('## Exact Commands')
    for item in packet.get('exact_commands', []):
        lines.append(f"- {item}")
    lines.append('')
    lines.append('## Expected Outputs')
    for item in packet.get('expected_outputs', []):
        lines.append(f"- {item}")
    validation_command = packet.get('validation_command')
    if isinstance(validation_command, str) and validation_command:
        lines.append('')
        lines.append('## Validation Command')
        lines.append(f"`{validation_command}`")
    lines.append('')
    lines.append('## Done When')
    for item in packet.get('done_when', []):
        lines.append(f"- {item}")
    hints = packet.get('troubleshooting', [])
    if isinstance(hints, list) and hints:
        lines.append('')
        lines.append('## Troubleshooting')
        for item in hints:
            lines.append(f"- {item}")
    return '\\n'.join(lines) + '\\n'

def _mark_waiting_human(manifest: dict[str, object], stage_id: str, attempt: int, waiting_payload: dict[str, object]) -> None:
    for row in _stage_rows(manifest):
        if str(row.get('stage_id', '')) != stage_id:
            continue
        row['status'] = 'waiting_human'
        row['attempt'] = attempt
        row['updated_at'] = now_rfc3339()
        row['waiting_human'] = waiting_payload
        manifest['failure_stage_id'] = None
        _write_manifest(manifest)
        return
    raise ValueError(f'run manifest missing stage row for {stage_id}')

def _human_stage_waiting(
    manifest: dict[str, object],
    run_id: str,
    pipe_root: str,
    stage_id: str,
    instructions: dict[str, object],
    required_inputs: list[str],
    expected_outputs: list[dict[str, object]],
    attempt: int,
) -> bool:
    json_path, md_path, marker_path = _task_paths(run_id=run_id, stage_id=stage_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    required_inputs = [str(Path(path).as_posix()) for path in required_inputs]
    expected_paths = [str(Path(item.get('path', '')).as_posix()) for item in expected_outputs if isinstance(item, dict) and item.get('path')]
    raw_steps = instructions.get('steps', [])
    raw_done_when = instructions.get('done_when', [])
    troubleshooting = instructions.get('troubleshooting', [])
    scope = {'run_id': run_id, 'stage_id': stage_id}
    def _fmt(text: str) -> str:
        rendered = text
        for key, value in scope.items():
            rendered = rendered.replace('{' + key + '}', str(value))
        return rendered
    packet = {
        'task_id': f'{run_id}:{stage_id}',
        'run_id': run_id,
        'stage_id': stage_id,
        'purpose': _fmt(str(instructions.get('summary', ''))),
        'required_inputs': required_inputs,
        'exact_commands': [_fmt(str(item)) for item in raw_steps if isinstance(item, str)],
        'expected_outputs': expected_paths,
        'validation_command': _fmt(str(instructions.get('validation_command', ''))) if instructions.get('validation_command') else None,
        'done_when': [_fmt(str(item)) for item in raw_done_when if isinstance(item, str)],
        'troubleshooting': [_fmt(str(item)) for item in troubleshooting if isinstance(item, str)],
        'generated_at': now_rfc3339(),
    }
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + '\\n')
    md_path.write_text(_render_task_packet_markdown(packet))
    output_missing = [path for path in expected_paths if not Path(path).exists()]
    validation_error: str | None = None
    if not output_missing:
        try:
            cfg = {'run_id': run_id}
            if pipe_root:
                cfg['_pipe_root'] = pipe_root
            ctx = StageContext.make_base(run_config=cfg).for_stage(stage_id, expected_outputs=expected_outputs)
            outputs_to_validate = [str(item.get('path', '')) for item in expected_outputs if item.get('path')]
            ctx.validate_outputs(stage_id, outputs_to_validate)
            ctx.validate_expected_outputs(stage_id)
        except Exception as exc:
            validation_error = str(exc)
    waiting_payload = {
        'task_id': str(packet['task_id']),
        'task_packet_json': json_path.as_posix(),
        'task_packet_md': md_path.as_posix(),
        'marker_path': marker_path.as_posix(),
        'expected_outputs': expected_paths,
        'validation_status': {
            'missing_outputs': output_missing,
            'error': validation_error,
            'ok': (not output_missing) and (validation_error is None),
        },
        'blocked_at': now_rfc3339(),
    }
    if output_missing or validation_error:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text('waiting_human\\n')
        _mark_waiting_human(manifest=manifest, stage_id=stage_id, attempt=attempt, waiting_payload=waiting_payload)
        return True
    if marker_path.exists():
        marker_path.unlink()
    return False

def _stage_rows(manifest: dict[str, object]) -> list[dict[str, object]]:
    return _MANIFEST_REPO.stage_rows(manifest)

def _artifact_index(manifest: dict[str, object]) -> dict[str, str]:
    raw = manifest.get('artifact_index', {})
    if not isinstance(raw, dict):
        raise ValueError('run manifest field artifact_index must be an object')
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError('run manifest artifact_index entries must be string:string')
        out[key] = value
    return out

def _active_item_ids(manifest: dict[str, object]) -> list[str]:
    raw = manifest.get('active_item_ids', [])
    if not isinstance(raw, list):
        return []
    return [str(item_id) for item_id in raw]

def _item_attempts(manifest: dict[str, object]) -> dict[str, dict[str, int]]:
    raw = manifest.get('item_attempts', {})
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, dict[str, int]] = {}
    for stage_id, by_item in raw.items():
        if not isinstance(stage_id, str) or not isinstance(by_item, dict):
            continue
        out[stage_id] = {}
        for item_id, value in by_item.items():
            if not isinstance(item_id, str):
                continue
            try:
                out[stage_id][item_id] = int(value)
            except Exception:
                out[stage_id][item_id] = 0
    return out

def _next_item_attempt(manifest: dict[str, object], stage_id: str, item_id: str) -> int:
    attempts = _item_attempts(manifest)
    stage_attempts = attempts.setdefault(stage_id, {})
    current = int(stage_attempts.get(item_id, 0))
    stage_attempts[item_id] = current + 1
    manifest['item_attempts'] = attempts
    return current + 1

def _stage_index(stage_id: str) -> int:
    try:
        return STAGES.index(stage_id)
    except ValueError as exc:
        raise ValueError(f'unknown stage id in run manifest: {stage_id}') from exc

def _first_incomplete_stage(manifest: dict[str, object]) -> str | None:
    for row in _stage_rows(manifest):
        stage_id = str(row.get('stage_id', ''))
        status = str(row.get('status', 'pending'))
        if status != 'completed':
            return stage_id
    return None

def _mark_stage(manifest: dict[str, object], stage_id: str, status: str, attempt: int, error: object | None = None) -> None:
    for row in _stage_rows(manifest):
        if str(row.get('stage_id', '')) != stage_id:
            continue
        row['status'] = status
        row['attempt'] = attempt
        row['updated_at'] = now_rfc3339()
        if error is not None:
            row['error'] = error
        elif 'error' in row:
            del row['error']
        manifest['failure_stage_id'] = stage_id if status == 'failed' else None
        _write_manifest(manifest)
        return
    raise ValueError(f'run manifest missing stage row for {stage_id}')

def _register_stage_outputs(manifest: dict[str, object], stage_id: str, loop_iteration: int, outputs: list[str]) -> None:
    if loop_iteration < 1:
        raise ValueError('loop iteration must be >= 1')
    index = _artifact_index(manifest)
    for output_name in outputs:
        rel_path = Path(output_name)
        if rel_path.is_absolute():
            raise ValueError(
                f"pipeline '{PIPELINE_ID}' stage '{stage_id}' loop snapshot path '{output_name}' must be relative to run dir"
            )
        if any(part == '..' for part in rel_path.parts):
            raise ValueError(
                f"pipeline '{PIPELINE_ID}' stage '{stage_id}' loop snapshot path '{output_name}' must not escape run dir"
            )
        src = rel_path
        if not src.exists():
            raise FileNotFoundError(
                f"pipeline '{PIPELINE_ID}' stage '{stage_id}' missing output '{output_name}' needed for snapshot"
            )
        dst = Path(stage_id) / 'loops' / f'{loop_iteration:04d}' / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        index[output_name] = dst.as_posix()
    manifest['artifact_index'] = index
    manifest['loop_iteration'] = loop_iteration
    _write_manifest(manifest)

def _ensure_manifest_stages(manifest: dict[str, object]) -> None:
    manifest_stage_ids = [str(row.get('stage_id', '')) for row in _stage_rows(manifest)]
    if manifest_stage_ids != STAGES:
        raise ValueError('run manifest stage order does not match compiled flow')

def _resolve_resume_index(run_config: dict[str, object], manifest: dict[str, object]) -> int:
    resume_stage = run_config.get('_resume_stage_id')
    if isinstance(resume_stage, str) and resume_stage:
        return _stage_index(resume_stage)
    failure_stage = manifest.get('failure_stage_id')
    if isinstance(failure_stage, str) and failure_stage:
        return _stage_index(failure_stage)
    first_incomplete = _first_incomplete_stage(manifest)
    if first_incomplete is None:
        return len(STAGES)
    return _stage_index(first_incomplete)

def _should_run_stage(manifest: dict[str, object], stage_id: str, stage_index: int, resume_index: int) -> bool:
    if stage_index < resume_index:
        return False
    for row in _stage_rows(manifest):
        if str(row.get('stage_id', '')) != stage_id:
            continue
        return str(row.get('status', 'pending')) != 'completed'
    return True

def _resolve_loop_target(stage_id: str) -> str | None:
    go_to = STAGE_GO_TO.get(stage_id)
    if not isinstance(go_to, str) or not go_to:
        return None
    target = REENTRY_TO_STAGE.get(go_to)
    return target if isinstance(target, str) and target else None

def _iter_stage_items(ctx: StageContext, items_artifact: str, keys: dict[str, str] | None, active_item_ids: set[str] | None):
    for item in iter_items_deterministic(ctx, items_artifact=items_artifact, keys=keys):
        item_id = str(item.get('item_id', ''))
        if active_item_ids is not None and item_id not in active_item_ids:
            continue
        yield item
"""

_FLOW_RUN_PREFIX = """
def run(run_config: dict[str, object], attempt: int = 1) -> int:
    run_id = str(run_config['run_id'])
    run_config.setdefault('_pipe_root', str(Path(__file__).resolve().parents[1]))
    manifest = _read_manifest(run_id)
    _ensure_manifest_stages(manifest)
    loop_iteration_raw = run_config.get('_loop_iteration', manifest.get('loop_iteration', 1))
    loop_iteration = int(loop_iteration_raw) if isinstance(loop_iteration_raw, int) or str(loop_iteration_raw).isdigit() else 1
    if loop_iteration < 1:
        loop_iteration = 1
    active_from_manifest = _active_item_ids(manifest)
    active_from_config = run_config.get('_active_item_ids')
    if isinstance(active_from_config, list):
        active_item_ids = {str(item_id) for item_id in active_from_config}
    elif active_from_manifest:
        active_item_ids = {str(item_id) for item_id in active_from_manifest}
    else:
        active_item_ids = None
    run_config['_loop_iteration'] = loop_iteration
    run_config['_artifact_index'] = _artifact_index(manifest)
    resume_index = _resolve_resume_index(run_config=run_config, manifest=manifest)
    if resume_index >= len(STAGES):
        return 0
    cycle_start_index = resume_index
    while True:
        loop_continue = False
        next_cycle_start_index = cycle_start_index
        next_active_item_ids: list[str] = []
        loop_origin_stage: str | None = None
        run_config['_loop_iteration'] = loop_iteration
        run_config['_active_item_ids'] = sorted(active_item_ids) if active_item_ids is not None else []
        run_config['_artifact_index'] = _artifact_index(manifest)
        ctx_base = StageContext.make_base(run_config=run_config)
"""

_FLOW_RUN_SUFFIX = """
        if loop_continue:
            if PIPELINE_TYPE != 'looping':
                raise RuntimeError(f'loop jump requested in straight pipeline {PIPELINE_ID}')
            if MAX_LOOPS <= 0:
                raise RuntimeError(f'loop jump requested but max_loops is 0 for pipeline {PIPELINE_ID}')
            if loop_iteration >= MAX_LOOPS:
                raise RuntimeError(
                    f'pipeline {PIPELINE_ID} stage {loop_origin_stage or "<unknown>"} exceeded max_loops={MAX_LOOPS}'
                )
            loop_iteration += 1
            cycle_start_index = next_cycle_start_index
            active_item_ids = set(next_active_item_ids)
            manifest['active_item_ids'] = sorted(active_item_ids)
            manifest['loop_iteration'] = loop_iteration
            _write_manifest(manifest)
            continue
        manifest['active_item_ids'] = []
        manifest['loop_iteration'] = loop_iteration
        _write_manifest(manifest)
        return 0

def main() -> None:
    parser = argparse.ArgumentParser(description='Run generated Seedpipe flow')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--attempt', type=int, default=1)
    args = parser.parse_args()
    code = run(run_config={'run_id': args.run_id}, attempt=args.attempt)
    raise SystemExit(code)

if __name__ == '__main__':
    main()
"""


