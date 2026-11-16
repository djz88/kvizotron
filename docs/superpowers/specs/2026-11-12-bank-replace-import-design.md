# Replace the questions of a bank by an import — design

Date: 2026-11-12. Status: approved in conversation ("1 ano"; the second question, who uses a bank, is already answered by the refusal message of a bank delete and is reused on the check page).

## Why

An import into a bank only adds questions, so updating a bank from a corrected file leaves the old questions beside the new ones. A bank that quizzes already draw from cannot be deleted and recreated, because a quiz holds a draw row by bank id. Published revisions keep their own copies (AC-32), so replacing the questions of a bank does not touch any run, running or closed.

## What

1. **A second entry on the bank page**, "Replace questions", next to "Import questions" (shown when imports are available and the bank has at least one question). It opens the same upload page with the target `bank_replace:<bank id>`; the page says the questions of the bank will be replaced.
2. **The check page** for this target shows how many questions of the bank will be deleted and how many the file adds, which quizzes draw from the bank (the same list the bank delete refusal gives) and that their published questions stay as they are while the draw row shows an unpublished change. The button reads "Replace the questions".
3. **Replace = add the file's questions, then delete the questions the bank held before**, in one transaction. Folders are never deleted, so draw rows that name a folder keep working; folders missing for a path are created as usual. The bank id does not change, so draw rows keep working too.
4. **Strict.** A file with any row error is refused on the check page ("Fix the rows and upload again; nothing was changed"). A failure while saving, such as a folder error, rolls everything back and the report says nothing was replaced. A file with no usable question deletes nothing (as an import creates nothing then). Warnings do not refuse.
5. **Audit and report.** `import.applied` gets `replaced: true` and `removed: N` (counts only). The report shows "Questions removed: N" beside "Questions added".
6. **Docs.** AC-165, addendum to ADR-0045, README range `AC-01…AC-165`, a line in `app/domain/CLAUDE.md`, Czech and Ukrainian translations.

## Not in scope

- Matching old and new questions to update them one by one (no stable key in the file).
- Replacing the questions of a draft or a new quiz.
- Deleting a bank that quizzes use (stays refused; the message already names the quizzes).
- Removing images of the deleted questions (as for a single deleted question today).

## Calls made here

- The target is a distinct kind, `bank_replace`, instead of a checkbox, so the confirmation page always shows which mode runs and "Upload another file" keeps the mode.
- New questions are saved before the old ones are deleted, and only the ids that existed before the import are deleted.
- A refusal on any row error is chosen over "skip bad rows", because a skipped row would delete its old question without a replacement.
