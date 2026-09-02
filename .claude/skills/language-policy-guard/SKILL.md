---
name: language-policy-guard
description: Guard skill — when a project declares a single language for code and artifacts, sweep the change for text in another language leaking into identifiers, comments, docstrings, log messages, commit messages, test names and user-facing strings. Driven entirely by `user_overrides.language_policy` in the project profile; when the policy is absent or disabled, this skill does nothing. Read before committing and after producing more than ~20 lines. Triggers on phrases "check the language policy", "проверь язык кода". MUST NOT flag files listed as legitimate foreign-language data, and MUST NOT activate at all when no policy is configured.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/language-policy/language-policy-guard
user-invocable: true
disable-model-invocation: false
---

## Configuration

```yaml
user_overrides:
  language_policy:
    enabled: true
    policy_language: en
    foreign_data_locations:
      - locales/**
      - tests/fixtures/i18n/**
```

`enabled: false` is the default. A project that has not declared a policy does not get one
invented for it — and an agent enforcing an undeclared rule is exactly the behaviour that makes
a team disable the whole skillset.

## Why this matters more for an AI teammate

A human working in their second language leaks occasionally and notices. A model prompted with a
ticket written in one language and a codebase written in another leaks systematically: a
variable named in the ticket's language, a comment translated halfway, a log message in the
wrong one. The result is a diff that reads as obviously machine-written, which is a real cost
even when the code is correct.

## What to sweep

| Surface | Check |
|---|---|
| identifiers | variables, functions, classes, files |
| comments and docstrings | the whole change |
| log and exception messages | including the ones only reached on failure |
| test names and fixture data | test names especially — they leak most |
| commit messages and the PR description | the parts a reviewer reads first |
| user-facing strings | unless the project's i18n mechanism owns them |

## Carve-outs

Files in `foreign_data_locations` legitimately hold other-language content: translation
catalogues, fixtures mirroring an external system, test data from a real source. Never flag
them, and never "fix" them.

Domain terms with no accepted translation stay as they are. Enforcing a policy into nonsense is
worse than the leak.

## Output

Findings, not edits, when running for the reviewer; direct fixes when running for the executor
before a commit. Either way the report names the surface and the line:

```
language-policy: 3 items
- reports/export.py:44 comment in ru
- tests/test_export.py:12 test name in ru
- commit message "добавил экспорт"
```
