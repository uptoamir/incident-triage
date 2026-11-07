# How the plan got made

Before any code, I had several AI agents plan this independently and then review each other's work.

1. Four separate agent sessions each read the brief and wrote a plan, no code: `1.md`, `2.md`, `3.md`, `4.md`.
2. Claude Code compared the four. It ranked 2.md first and 4.md close behind.
3. Two more agents reviewed all four on their own: `1-agent-feedback.md`, `2-agent-feedback.md`. Agent 2 ran small SQLite and regex checks to reproduce the bugs it found.
4. Claude Code merged everything into one plan, using 4.md as the base, since both reviewers picked it.
5. The same two agents reviewed the merged plan (`1-agent-5-feedback.md`, `2-agent-5-feedback.md`), and the fixes went back in.
6. That plan is `../PLAN.md`, minus its header and an interview-prep section.

Every review point and what was decided about it: PLAN.md §20 (56 items).

Bugs this caught before any code existed:
- 4.md scanned for `INC-\d{5}`, so an invented `INC-9999` would get past the guardrail.
- 4.md's "specific values" check matched incident IDs as error codes. In strict mode that would delete the citations the brief requires. Reproduced with `re.findall`.
- 3.md used a `:memory:` test DB with one connection per request, so every request sees an empty database. Reproduced.
- All four plans: `tags=db&tags=db` returned nothing. Reproduced.
- The merged plan: `LLM_TEMPERATURE=none`, its own advice for models that reject temperature, crashed startup with plain pydantic-settings. Reproduced.
- The merged plan: the free-text ID check ran before the evidence check dropped incidents, so a dropped incident could still be named in the answer.

4.md had a role-play "Author" line in its header that came from the prompt. I removed it. `2-agent-feedback.md` still mentions it.
