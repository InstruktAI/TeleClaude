---
description: Find out what to do next and continue WIP or break down todo story into PRD + tasks. Start here if asked to do work.
---

You are now in **WORK mode**. Your output is ALWAYS working code that is covered by tests.

Follow these steps to find out what to do next:

## Step 1: Fix Bugs FIRST

1. Open `todos/bugs.md` to see if there are any open bugs (unchecked items).
2. If there are open bugs, pick the first one and work on fixing it.
3. Work on fixing all open bugs before moving on.

## Step 2: Continue Work In Progress (WIP) or start new task

1. Read the `todos/roadmap.md` file to see which story is checked last and remember its title.
2. Find corresponding `todos/{slug}.md` file and see what task is checked last.
3. Check the status of that task, by first checking git commits, and then the code that goes with it.
4. Find out what is missing or incomplete in that task, and complete it first.
5. Ready to commit and even deploy?
   - If commit is warranted AND can be deployed, call `/commit-deploy`.
   - If just a commit needs to happen, call `/commit`.
     Call these commands first time only, next time just do it.
6. Mark task as done (checked), then move on to the next.
7. Finish all tasks, and mark the story as complete in `todos/roadmap.md`.

## Step 3: If no WIP, create PRD + task breakdown for next roadmap item

1. Read `todos/roadmap.md` to find the first unchecked item.
2. Generate a comprehensive PRD for that item in `prds/{slug}.md`, by calling `/next-prd`.
3. Create a detailed task breakdown in `todos/{slug}.md`, by calling `/next-breakdown`.
4. Start working on the first task in the breakdown by going to [Step 1](#step-1-continue-work-in-progress-wip-or-start-new-task).
