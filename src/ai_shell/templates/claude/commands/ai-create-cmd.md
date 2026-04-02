Create a new Claude command for trinity repositories: $ARGUMENTS

Follow these steps to create a well-structured command:

1. **Parse the command request**:
   ```
   Extract from user input:
   - Command name (kebab-case)
   - Command purpose
   - Key functionality needed
   - Target repos (default: all trinity)
   ```

2. **Determine command scope**:
   - **Trinity command**: For augint-library, augint-api, augint-web
   - **Meta command**: Only if it makes sense for augint-project management

   Ask: "Should this command also have a meta version for the augint-project repo?"
   (Only if the command relates to project management, vision docs, or cross-repo operations)

3. **Create the command file**:
   ```bash
   # Create in vision templates first
   touch vision/templates/claude-config/commands/{command-name}.md
   ```

4. **Generate command template** with this structure:
   ```markdown
   {Command description in active voice}: $ARGUMENTS

   Follow these steps:

   1. **{First major step}**:
      - {Specific action}
      - {Validation check}
      ```bash
      # Example command
      ```

   2. **{Second major step}**:
      - {Specific action}
      - {Error handling}

   3. **{Output/Report}**:
      ```
      === {Command Name} Results ===

      {Structured output format}

      Status: {success/warnings/failures}
      ```

   ## Why This Matters
   {1-2 sentences on the value this provides}

   ## Example Usage
   /command-name specific arguments
   ```

5. **Add command metadata**:
   - Purpose statement
   - Required tools (Bash, Git, GitHub API, etc.)
   - Expected inputs/outputs
   - Error conditions

6. **Validate the command**:
   ```bash
   # Check syntax
   cat .claude/commands/{command-name}.md

   # Verify it follows patterns
   grep -E "(Follow these steps|Why This Matters)" .claude/commands/{command-name}.md
   ```

7. **Common command patterns to include**:
   - **Discovery commands**: Use Task tool for complex searches
   - **Action commands**: Include verification steps
   - **Report commands**: Structured output format
   - **Workflow commands**: Step-by-step with checkpoints

8. **Best practices**:
   - Keep commands focused on one primary task
   - Use active voice ("Create PR" not "PR should be created")
   - Include example output
   - Add "Why This Matters" section
   - Make steps explicit and numbered
   - Include verification/rollback steps

9. **Copy to trinity repositories**:
   ```bash
   # Copy to all trinity repos
   for repo in augint-library augint-api augint-web; do
     cp vision/templates/claude-config/commands/{command-name}.md ../$repo/.claude/commands/
   done

   # If meta command was created
   if [ -f vision/templates/claude-config/commands/{command-name}-meta.md ]; then
     cp vision/templates/claude-config/commands/{command-name}-meta.md .claude/commands/{command-name}.md
   fi
   ```

10. **Verify deployment**:
    ```bash
    # Check all trinity repos have the command
    ls -la ../augint-*/.claude/commands/{command-name}.md

    # Check meta command if applicable
    ls -la .claude/commands/{command-name}.md 2>/dev/null || echo "No meta command created"
    ```

## Template Examples

### For Git Workflow Commands:
```markdown
{Action} for {purpose}: $ARGUMENTS

Follow these steps:
1. **Check current state**
2. **Perform action**
3. **Verify success**
4. **Report results**
```

### For Analysis Commands:
```markdown
Analyze {target} for {criteria}: $ARGUMENTS

Follow these steps:
1. **Gather data**
2. **Process and categorize**
3. **Generate insights**
4. **Provide recommendations**
```

### For Automation Commands:
```markdown
Automate {task} across {scope}: $ARGUMENTS

Follow these steps:
1. **Validate prerequisites**
2. **Execute automation**
3. **Handle errors**
4. **Confirm completion**
```

## Why This Matters
Trinity-wide command deployment ensures consistent tooling across all repositories, reducing maintenance overhead and ensuring all projects have access to the same automation capabilities.
