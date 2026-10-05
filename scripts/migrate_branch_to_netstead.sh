#!/usr/bin/env bash
# Move a pre-rename branch (gmnspy/datagrove, based on refactor/v1.0 @ 0480ad1) onto the
# renamed main (netstead/corral), keeping the branch's history.
#
#   1. Commit your work-in-progress so `git status` is clean.
#   2. From the branch's worktree:   bash <(git show origin/main:scripts/migrate_branch_to_netstead.sh)
#   3. If it stops on conflicts: resolve them, `git add` the files, then run it again with --finish.
#   4. Run both test suites, then open a PR against main.
#
# Why not just `git merge origin/main`? Both sides renamed every file, so any line the branch
# edited that mentions gmnspy/datagrove conflicts with the rename. Instead we rename the branch
# tip with the same script, take the branch's own changes as a diff against the tagged
# `rename-base` (the mechanical rename of 0480ad1), and replay that diff onto origin/main. Only
# real overlaps with main's post-rename edits can conflict. The result is committed as a merge
# of (renamed branch tip, origin/main).
set -euo pipefail

OLD_BASE=0480ad1a7cb4b41b0386ca3f2df1368a14946fc4
STATE="$(git rev-parse --git-dir)/netstead-migrate"

finish() {
  local branch renamed_tip merge
  read -r branch renamed_tip < "$STATE"
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    echo "Unresolved conflicts remain:" >&2; git diff --name-only --diff-filter=U >&2; exit 1
  fi
  git add -A
  merge=$(git commit-tree "$(git write-tree)" -p "$renamed_tip" -p origin/main \
    -m "Merge main into $branch: netstead/corral rename")
  git reset -q --hard
  git switch -q "$branch"
  git merge -q --ff-only "$merge"
  rm -f "$STATE"
  echo "Done: $branch is now based on main. Next: uv sync --all-packages --all-extras, then run both test suites."
}

if [ "${1:-}" = "--finish" ]; then finish; exit; fi

git fetch -q origin main 'refs/tags/rename-base:refs/tags/rename-base'
branch=$(git symbolic-ref --short HEAD)
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Commit your changes first." >&2; exit 1; }
git merge-base --is-ancestor "$OLD_BASE" HEAD || { echo "$branch is not based on refactor/v1.0 @ 0480ad1." >&2; exit 1; }
! git cat-file -e HEAD:packages/netstead 2>/dev/null || { echo "$branch is already renamed." >&2; exit 1; }

# 1. Rename the branch tip exactly as main was renamed.
git show origin/main:scripts/rename_to_netstead.py > scripts/rename_to_netstead.py
python3 scripts/rename_to_netstead.py
uv lock -q
uv run ruff format -q . || true
uv run ruff check --fix -q . || true
git add -A
git commit -q --no-verify -m "chore: apply netstead/corral rename"
renamed_tip=$(git rev-parse HEAD)
echo "$branch $renamed_tip" > "$STATE"

# 2. Replay the branch's own changes (in renamed space) onto origin/main.
work=$(git commit-tree "$renamed_tip^{tree}" -p refs/tags/rename-base -m "$branch changes, renamed")
git switch -q --detach origin/main
if ! git cherry-pick --no-commit "$work"; then
  echo
  echo "Conflicts above overlap with main's post-rename edits. Resolve them, git add, then rerun with --finish."
  echo "(uv.lock: git checkout --theirs uv.lock && uv lock && git add uv.lock)"
  exit 2
fi
finish
