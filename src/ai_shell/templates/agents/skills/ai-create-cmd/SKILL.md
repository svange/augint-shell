---
name: ai-create-cmd
description: Create a new agent skill using the AGENTS.md open standard. Use when building new automation commands or skills.
argument-hint: "[skill-name and description]"
---

Create a new agent skill for the repository: $ARGUMENTS

Follow these steps to create a well-structured skill:

1. **Parse the skill request**:
   ```
   Extract from user input:
   - Skill name (kebab-case)
   - Skill purpose
   - Key functionality needed
   ```

2. **Create the skill directory and file**:
   ```bash
   # Create in .agents/skills/ (cross-platform standard)
   mkdir -p .agents/skills/{skill-name}
   touch .agents/skills/{skill-name}/SKILL.md
   ```

3. **Generate SKILL.md** with this structure:
   ```markdown
   ---
   name: {skill-name}
   description: {One-line description of what it does and when to use it. Max 250 chars.}
   argument-hint: "[expected arguments]"
   ---

   {Command description in active voice}: $ARGUMENTS

   {Brief overview of what this skill does.}

   ## Usage Examples
   - `/{skill-name}` - Default behavior
   - `/{skill-name} specific args` - With arguments

   ## 1. {First Major Step}
   - {Specific action}
   - {Validation check}
   ```bash
   # Example command
   ```

   ## 2. {Second Major Step}
   - {Specific action}
   - {Error handling}

   ## 3. {Output/Report}
   ```
   === {Skill Name} Results ===

   {Structured output format}

   Status: {success/warnings/failures}
   ```

   ## Error Handling
   - {Error condition}: {Recovery action}
   ```

4. **Choose appropriate frontmatter options**:
   - `argument-hint` to show expected arguments in the skill menu
   - Keep description under 250 characters, front-load key use case

5. **Validate the skill**:
   ```bash
   # Check SKILL.md exists and has frontmatter
   head -10 .agents/skills/{skill-name}/SKILL.md

   # Verify frontmatter has required fields
   grep -E "^(name|description):" .agents/skills/{skill-name}/SKILL.md
   ```

6. **Best practices**:
   - Keep skills focused on one primary task
   - Use active voice ("Create PR" not "PR should be created")
   - Include usage examples
   - Make steps explicit and numbered
   - Include error handling section
   - Reference related skills (e.g., "Next: `/ai-submit-work`")
   - Keep SKILL.md under 500 lines
   - Be directive, not conversational

7. **Cross-platform compatibility**:
   The `.agents/skills/` directory follows the AGENTS.md open standard.
   Skills placed here are discovered by:
   - **Codex CLI**: reads `.agents/skills/` natively
   - **opencode**: reads `.agents/skills/` as a fallback
   - **Claude Code**: reads `.claude/skills/` (copy there for Claude support)

## Skill Patterns

### For Git Workflow Skills:
```markdown
{Action} for {purpose}: $ARGUMENTS

## 1. Check current state
## 2. Perform action
## 3. Verify success
## 4. Report results with next step
```

### For Analysis Skills:
```markdown
Analyze {target} for {criteria}: $ARGUMENTS

## 1. Gather data
## 2. Process and categorize
## 3. Generate insights
## 4. Provide recommendations
```

### For Automation Skills:
```markdown
Automate {task} across {scope}: $ARGUMENTS

## 1. Validate prerequisites
## 2. Execute automation
## 3. Handle errors
## 4. Confirm completion
```
