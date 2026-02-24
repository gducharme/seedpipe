# seedpipe

`seedpipe` can be installed directly from a local checkout without publishing to PyPI.

## Install from a local path

From another project, add this repository as a local dependency:

```bash
python -m pip install /path/to/seedpipe
```

For editable development installs:

```bash
python -m pip install -e /path/to/seedpipe
```

## What gets installed

- `seedpipe` package.
- `tools` package (including `tools.compile`).
- `seedpipe-compile` CLI entrypoint.

After install, you can run:

```bash
seedpipe-compile --help
```

Or import in Python:

```python
from tools.compile import compile_pipeline, CompilePaths
```
