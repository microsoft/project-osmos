# Python helper runtime

Read this reference before invoking any script under
`skills/project-osmos/scripts/`.

The packaged helpers use only the Python standard library. They do not require
third-party packages, a dependency sync, or a dedicated Project Osmos virtual
environment. They require Python 3.11 or newer.

## Select one existing interpreter

Resolve the runner once and reuse it for every helper in the run, including
the detached dashboard poller:

1. If a virtual environment or Conda environment is active, use its `python`
   from the current `PATH` when it is Python 3.11 or newer.
2. Otherwise, if the current project already has a `uv`-managed environment,
   use `uv run --no-sync python` when that interpreter is Python 3.11 or newer.
   Use `--active` when an active environment must take precedence over the
   project's environment.
3. Otherwise, scan the existing `python` and `python3` executables across
   `PATH` in order, deduplicate aliases to the same interpreter, and use the
   first Python 3.11+ candidate.

Do not invoke `uv run` unless the `uv` environment already exists. Do not
create `.venv`, alter dependency manifests or lockfiles, or switch
interpreters partway through the task.

Each helper enforces the same minimum before doing work. An older interpreter
exits once with a message that names its path and version. Report that message
without retrying through package installation or environment creation.

## Never install dependencies

Do not run `pip install`, `python -m pip install`, `uv sync`, `uv add`,
`uv pip install`, Conda package installation, or any equivalent dependency
mutation for Project Osmos helpers.

If a helper fails to import a standard-library or sibling helper module,
surface the interpreter path, Python version, command, and original error
once. Treat it as an incompatible interpreter or invocation-path problem, not
as a missing package to install.

This contract applies only to the local plugin helpers. Do not add Python
environment or package-install instructions to the remote Project Osmos task.
