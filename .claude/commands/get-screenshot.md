---
description: Find and show the most recent screenshots from standard Windows locations. Usage: /get-screenshot [count] [all] (default: 3 from today)
argument-hint: [count] [all]
allowed-tools: [Bash, Read]
---

Find and display screenshots from standard Windows paths.

## Arguments
$ARGUMENTS may contain:
- A number (how many to read, default 3)
- The word `all` (remove the today-only date filter)
- Both, e.g. `10 all` or `all 10`

## Steps

### 1 — Resolve count and mode
Parse $ARGUMENTS:
- If a number is present, N = that number. Otherwise N = 3.
- If the word `all` is present (case-insensitive), set DATE_FILTER = false.
- Otherwise DATE_FILTER = true (today only).

### 2 — Find screenshots
First resolve the Windows username, then run the appropriate bash command:

**If DATE_FILTER = true (default):**
```bash
WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')
TODAY=$(date +%Y-%m-%d)
find \
  /mnt/c/Users/$WIN_USER/Pictures/Screenshots \
  /mnt/c/Users/$WIN_USER/OneDrive/Pictures/Screenshots \
  -maxdepth 1 \
  \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) \
  -newermt "$TODAY 00:00:00" \
  2>/dev/null \
| xargs -I{} stat --format="%Y %n" {} 2>/dev/null \
| sort -rn \
| head -10 \
| awk '{print $2}'
```

**If DATE_FILTER = false (`all` flag present):**
```bash
WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')
find \
  /mnt/c/Users/$WIN_USER/Pictures/Screenshots \
  /mnt/c/Users/$WIN_USER/OneDrive/Pictures/Screenshots \
  -maxdepth 1 \
  \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) \
  2>/dev/null \
| xargs -I{} stat --format="%Y %n" {} 2>/dev/null \
| sort -rn \
| head -10 \
| awk '{print $2}'
```

### 3 — Report what was found
List all results (up to 10) with their filenames and timestamps so the user
can see the full set. Format as a numbered list. Mention whether results are
from today only or all time.

### 4 — Read the top N
For each of the top N files (most recent first), use the Read tool to load
the image and display it inline.

### 5 — Contextual summary
After displaying the images, write 1-2 sentences relating what you see in
the screenshots to the current conversation context.
If no files were found, respond:
"No screenshots found in the standard Windows paths. You can share
a path manually using /mnt/c/Users/<you>/path/to/file."
