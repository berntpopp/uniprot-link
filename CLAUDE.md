# CLAUDE.md

@AGENTS.md

Claude Code entrypoint:

- Use `AGENTS.md` for shared instructions.
- Run `make ci-local` before final handoff.
- When changing SPARQL query builders in `uniprot_link/services/queries.py`,
  re-validate against the live endpoint with `python research/verify_queries.py`
  (QLever has sharp timeout edges — see AGENTS.md "SPARQL / QLever Discipline").
