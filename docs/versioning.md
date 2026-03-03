# Versioning Policy

This project follows semantic versioning with practical release discipline.

## Rules

- Patch (`x.y.Z`): docs-only updates, typo fixes, non-functional wording updates.
- Minor (`x.Y.z`): new non-breaking features, new contracts, new pipeline capabilities that preserve compatibility.
- Major (`X.y.z`): breaking contract changes, incompatible runtime behavior, or required migration steps.

## Current Guidance

- For seedpipe-8b30 (docs/version hygiene), use a patch bump.
- Today: `0.2.21` -> `0.2.22`.

## Release Checklist

1. Update `CHANGELOG.md` with dated entry.
2. Bump version in `pyproject.toml`.
3. Ensure docs and specs references are aligned.
4. Run baseline tests before merge.
