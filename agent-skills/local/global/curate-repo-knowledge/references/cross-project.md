# Cross-Project Alignment

Use only when a changed contract has a declared dependency or direct consumer outside the current repository.

1. Identify affected projects from manifests, submodules, API/SDK references, deployment configuration, or explicit repository docs.
2. Name the changed contract: API, schema, environment variable, command, artifact, package, or operational dependency.
3. Inspect only the consumer authority that owns that contract or its integration instructions.
4. Update the producer authority first, then affected consumer documentation.
5. Validate links and examples on both sides; report inaccessible consumers as unresolved.

Do not scan unrelated projects, infer consumers from directory proximity, or copy producer internals into consumer docs. Require separate authorization before modifying a project outside the user's stated workspace or current write boundary.
