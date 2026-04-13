# augint-shell Round 13 Issues

Discovered during pre-apply standardization evaluation across ai-lls-lib, ai-lls-api, ai-lls-web (2026-04-13).
Target package: `augint-shell`. File against the augint-shell repo.

---

## S13-1 -- OIDC step dry-run message hardcodes "Python" regardless of detected repo language

**Severity:** Low -- cosmetic, but misleading in dry-run output
**Area:** Standardize engine, OIDC step dry-run message

### Symptom

Running `ai-tools standardize ai-lls-web --all --dry-run --json` returns:

```json
{
  "step": "oidc",
  "status": "NEEDS_ACTION",
  "message": "[dry-run] OIDC step would delegate to `/ai-setup-oidc` sub-skill. Python performs no AWS IAM changes regardless."
}
```

ai-lls-web is detected as `node/service`, not Python. The message says "Python performs
no AWS IAM changes regardless" for all three repos regardless of their detected language.

### Root cause

The OIDC step's dry-run message uses a hardcoded string that mentions Python instead of
interpolating the detected language/runtime from the detection step.

### Fix

Interpolate the detected language into the message, or use a language-neutral phrasing:

```
"[dry-run] OIDC step would delegate to `/ai-setup-oidc` sub-skill."
```

If there is a runtime-specific caveat (e.g., Python standardize truly does skip IAM changes),
conditionally include it only when the detected language matches.

### Reproduction

```bash
uv run ai-tools standardize ai-lls-web --all --dry-run --json
# Look at the oidc step -- message says "Python" for a node/service repo
```
