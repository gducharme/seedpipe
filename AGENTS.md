# Repository Agent Notes

- Any new feature or code fix should include a corresponding entry in the docs specs document.
- Any code change should at least increment the patch version; for larger features, consider incrementing the minor version.
- Before building or modifying a pipe, read `pipeline.yaml` to understand the format, requirements, and stage graph that the pipeline is supposed to satisfy.
- When you change `pipeline.yaml` or any related models, run `seedpipe-compile` to regenerate `generated/` so you can see the resulting structure before coding stages.
- Once the scaffold is regenerated, implement each stage using the compiled contracts—run `seedpipe-run` (or the appropriate stage invocation) to produce artifacts and schemas, replacing placeholders as needed before chaining the next stage.
- Follow this inspect-compile-implement-validate pattern for every new requirement so the pipe stays consistent and reproducible.
