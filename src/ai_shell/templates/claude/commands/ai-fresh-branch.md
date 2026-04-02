Create a fresh feature branch intelligently: $ARGUMENTS

Start new work without a GitHub issue by creating a well-named branch with proper setup.

## Usage Examples
- `/ai-fresh-branch` - Interactive branch creation
- `/ai-fresh-branch refactor auth logic` - Create branch with suggested name
- `/ai-fresh-branch feat/new-dashboard` - Use exact branch name

## 1. Analyze Current State

```bash
# Check for uncommitted changes
git status --porcelain
if [ -n "$(git status --porcelain)" ]; then
    echo "Warning: You have uncommitted changes"
    # Show what's changed
    git status -s

    # Offer to stash
    echo "Stash these changes before creating branch? [y/n]"
    # If yes: git stash push -m "WIP: Before creating $BRANCH_NAME"
fi

# Check current branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" == "main" ]] || [[ "$CURRENT_BRANCH" == "master" ]]; then
    echo "Warning: You're on $CURRENT_BRANCH. Creating feature branch..."
fi
```

## 2. Smart Branch Naming

If no branch name provided in $ARGUMENTS:
```bash
# Analyze recent commits for context
RECENT_COMMIT=$(git log -1 --pretty=%s 2>/dev/null || echo "")

# Suggest branch name based on context
echo "What are you working on?"
echo "1) feat/    - New feature"
echo "2) fix/     - Bug fix"
echo "3) docs/    - Documentation"
echo "4) refactor/ - Code improvement"
echo "5) test/    - Adding tests"
echo "6) chore/   - Maintenance"

# Get user choice and description
# Example: feat/user-authentication
```

If $ARGUMENTS contains description but no prefix:
```bash
# Auto-detect type from keywords
if [[ "$ARGUMENTS" =~ fix|bug|issue ]]; then
    PREFIX="fix"
elif [[ "$ARGUMENTS" =~ doc|readme ]]; then
    PREFIX="docs"
elif [[ "$ARGUMENTS" =~ test|spec ]]; then
    PREFIX="test"
elif [[ "$ARGUMENTS" =~ refactor|improve|clean ]]; then
    PREFIX="refactor"
else
    PREFIX="feat"
fi

# Create branch name
BRANCH_NAME="$PREFIX/$(echo "$ARGUMENTS" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')"
```

## 3. Create and Setup Branch

```bash
# Get default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@' || echo "main")

# Update from remote
echo "Updating $DEFAULT_BRANCH..."
git checkout $DEFAULT_BRANCH && git pull

# Create new branch
echo "Creating branch: $BRANCH_NAME"
git checkout -b $BRANCH_NAME

# Push and set upstream
echo "Setting up remote tracking..."
git push -u origin $BRANCH_NAME
```

## 4. Apply Stashed Changes (if any)

```bash
# If we stashed changes earlier
if [ "$STASHED" = true ]; then
    echo "Applying stashed changes..."
    git stash pop

    # Show what was applied
    git status -s
fi
```

## 5. Final Output

```
Created branch: feat/user-authentication
Tracking origin/feat/user-authentication
Ready to start development

Next steps:
   - Make your changes
   - Run tests: make test
   - When ready: /ai-ship

Tip: Your branch will be automatically linked to an issue if you reference one in your commits
```

## Smart Features
- Detects if you're in the middle of a rebase/merge
- Suggests contextual branch names
- Handles uncommitted changes gracefully
- Sets up remote tracking immediately
- Works seamlessly with /ai-ship when ready

## Error Handling
- **Rebase in progress**: Abort or continue rebase first
- **Uncommitted changes**: Offer to stash or commit
- **Network issues**: Warn about push failure but continue
- **Branch exists**: Suggest alternative name
