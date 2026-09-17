# Getting updates

GitHub is the source of truth: `https://github.com/dancane19-creator/fpldraftboard`.

## On the PC

```powershell
cd C:\Users\dcane\Downloads\fpldraftboard
git pull origin main
```

If the folder has local commits that were never pushed and the pull complains,
and you don't need them, take GitHub's version:

```powershell
git fetch origin
git reset --hard origin/main
```

## When Claude ships a change

Claude cannot push to GitHub, so a change arrives one of two ways:

- **A zip of the changed files.** On the phone or PC, open the repo on
  github.com → **+** → Upload files → pick the files → Commit. Uploading a
  file with the same name replaces it. A new workflow file goes in via
  **+** → Create new file, with the full path typed in the name box.
- **A git bundle** for the PC. `git pull C:\path\to\fpl-draft.bundle main`
  in the folder, then `git push origin main` so GitHub has it too.

Either way the scheduled build picks up the change on its next run.
