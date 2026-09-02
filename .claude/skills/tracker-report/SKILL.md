---
name: tracker-report
description: Reporting skill — write the run's outcome into the ticket using the one template every stage shares, containing only claims an artifact can back. Also formats the questions comment for intake and the unresolved-findings block when a review loop exhausted its rounds. Triggers at the end of every run, after the sentinel's verdict. MUST NOT move a Jira status (deterministic post-processing does that), MUST NOT record an approval, and MUST NOT fill a field it cannot confirm.
metadata:
  scope: project
  author: ai-worker
  adapted_from: spec-to-ship/git-delivery/jira-sync/jira-finalize
user-invocable: false
disable-model-invocation: false
---

## The template

```
<Stage> — <outcome>

Branch:       ai/<KEY>
PR:           <URL>
Commit:       <SHA>
Done:
- <item>
Checks:
- <check>: <actual status>
Not verified automatically:
- <what exactly>
Review findings (advisory):
- <finding> — <location>
Run:          <URL>
Next:         <what human action is expected>
```

Rules that give the template its value:

**Only fields an artifact backs.** A field the executor cannot confirm gets filled with
invention, and invention is worse than absence because people build on it. If you cannot point
at a commit, a run, a test result or an API response for a line, the line does not go in.

**"Not verified automatically" is mandatory and non-empty.** Visual appearance, behaviour at
scale, anything needing a device or a human's judgement, anything the local gate could not run.

**Advisory findings ride along.** They are not defects to hide; they are what the human reviewer
should look at first.

**Unresolved blocking findings are stated as unresolved**, with the number of attempts:

```
Unresolved after 2 correction rounds:
- criterion_untested: acceptance criterion 3 has no test
```

A clean report over a known defect is the single worst output this system can produce.

## Questions comment

```
ai-worker: I need <n> answers before I start

What I understood
<paragraph>

Assumptions I will proceed on unless you object
- <assumption> (<basis>)

Questions
1. <question>  (<option> / <option>)
   <what it changes>

Reply in a comment, then add `ai:proceed` on its own first line.
Questions used: <n> of <budget>.
```

The last two lines are load-bearing. The command line is how a human resumes the run; the budget
line is how they learn the asking is finite.

## Tone

Plain and short. No apologising, no enthusiasm, no restating the ticket back at length. The
reader is a busy person deciding what to do next, and the last line of the report — what human
action is expected — is the one they actually need.
