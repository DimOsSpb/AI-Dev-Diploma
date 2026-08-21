# Project instructions

## Goal

Complete the current assignment using the existing repository.
Prefer modifying the existing architecture over introducing new abstractions.

## Autonomous mode

Work autonomously.

Do NOT ask the user for permission to:
- read files
- inspect directories
- search the repository
- inspect git status/diff/log
- run tests
- run linters
- run existing project commands
- inspect configuration files

If information is needed, inspect the repository yourself.

Only ask the user a question when:
1. the repository contains genuinely conflicting requirements, or
2. an external secret/API key/credential is required, or
3. a destructive operation cannot be safely inferred.

Do not stop after inspecting files.
Do not merely describe what should be done.
After understanding the relevant code, implement the solution.

## Persistent task state

`.agent/TASK_STATE.md` is the persistent state of the implementation.

At the beginning of work:
- read `.agent/TASK_STATE.md`;
- continue from `Current task`;
- do not rediscover completed work.

After completing a logical implementation block:
- update `.agent/TASK_STATE.md`;
- mark completed requirements;
- record only important architectural decisions;
- record relevant files;
- record the latest verification result;
- set the next concrete task.

Do NOT update TASK_STATE.md after every tool call or small edit.

Keep TASK_STATE.md short.
It is a state snapshot, not a diary.

Never write model reasoning, conversation history, or verbose explanations into it.

## Repository exploration

Do NOT read the whole repository.

Start with:
1. git status
2. top-level directory listing
3. AGENTS.md
4. relevant source directories
5. existing tests
6. configuration/docker files only when relevant

Search before opening files.

Prefer:
- grep/ripgrep
- git grep
- file listings
- targeted file reads

Never dump large unrelated files into context.

When searching:
- search for symbols/classes/functions first
- open only the relevant sections
- avoid generated files
- avoid dependencies/vendor directories
- avoid lock files unless dependency changes are required

## Task execution

Use this loop:

1. Inspect
2. Identify relevant files
3. Make a short plan
4. Implement
5. Run the smallest relevant test/check
6. Inspect errors
7. Fix
8. Repeat

Do not spend multiple turns explaining the plan.

## Context discipline

Keep responses concise.

Do not repeat:
- file contents
- code that was already inspected
- the task description
- long explanations of obvious changes
- unchanged code

Before reading a large file, determine whether the required information can be obtained with search.

When context becomes large:

1. update `.agent/TASK_STATE.md`;
2. use `/compact` or allow automatic compaction;
3. continue implementation.

## Anti-loop rule

Do not repeat repository exploration.

Before using a tool, ask:

"Do I already have this information?"

If yes:
- do not search again;
- use the existing information;
- proceed with implementation.

Do not inspect the same file repeatedly unless:
- it changed;
- a relevant section was not previously inspected;
- a test failure requires it.

Do not repeat a failed approach more than once.

If an approach fails:
1. inspect the actual error;
2. identify the cause;
3. change the approach;
4. retry.

## Action bias

Prefer taking the next concrete action over explaining the action.

Bad:

"I will now inspect the ingestion architecture and consider how it
could potentially be extended..."

Good:

Search for `IngestionPipeline`.

Then inspect the matching implementation.

Then edit the relevant file.

Do not narrate tool usage.

## Tool output discipline

Treat tool output as expensive.

Never intentionally produce large tool outputs.

For repository inspection:

- use `rg` / `git grep` before opening files;
- use `git diff --stat` before `git diff`;
- use `git status --short` instead of full status;
- inspect targeted line ranges;
- never dump entire files unless the file is small;
- never dump generated files;
- never dump lock files;
- never dump `.git`, `.venv`, `node_modules`, build directories, caches or binaries.

If a command can produce a large result, constrain it with:
- `head`
- `tail`
- `sed -n`
- `rg -n`
- `git diff -- <specific files>`

Prefer 100 relevant lines over 2000 potentially relevant lines.

## Coding rules

Prefer the smallest change that satisfies the assignment.

Reuse existing:
- services
- configuration
- abstractions
- database models
- API patterns
- error handling
- tests

Do not rewrite working code without a reason.

Do not create duplicate implementations.

## Completion

A task is not complete when code has merely been written.

Before finishing:
- run relevant tests
- run lint/type checks if available
- inspect git diff
- verify that requirements from the assignment are covered

Final response should contain only:
1. what was changed
2. checks executed
3. remaining problems, if any
