---
name: Enforce Line Limit
description: Ensure that no source code file exceeds 300 lines of code.
---

# Enforce Line Limit

## Goal
Maintain a clean and maintainable codebase by ensuring that no single file exceeds 300 lines of code.

## Rules
1.  **Check Line Count**: Before finishing a task or creating a new file, check if the file exceeds 300 lines.
2.  **Refactor**: If a file exceeds 300 lines, you MUST refactor it.
    *   Split the file into smaller, logical modules.
    *   Extract classes or functions into separate files.
    *   Move utility functions to a `utils` module.
    *   Create a `handlers` directory for bot command/message handlers.
3.  **Exceptions**:
    *   Generated code (if absolutely necessary and marked as such).
    *   Configuration files that are long lists of constants (though these should ideally be split too).
4.  **Verification**: Run a check to ensure all files are under the limit.

## How to Check
You can use `find` and `wc` or a simple python script to check line counts.

```bash
# Example check in PowerShell
Get-ChildItem -Recurse -Filter *.py | ForEach-Object { $count = (Get-Content $_.FullName | Measure-Object -Line).Lines; if ($count -gt 300) { Write-Output "$($_.Name): $count lines (EXCEEDS LIMIT)" } }
```
