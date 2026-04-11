# Woxom Ecosystem Transformation Plan

Full decomposition of `reference/hwh-work/` into a serverless, GitOps, fully-tested ecosystem with shared identity and shared business logic.

## Architecture Decisions (2026-04-05)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| AWS accounts | Shared staging (`woxom-eco-staging`) + shared prod | Simplifies management, enables native cross-stack refs |
| Stack naming | `{Project}{Stage}{StackType}` (no Woxom prefix) | Avoids stuttering, unique in shared account |
| CF export naming | `{project}-{stage}-{ResourceName}` | Unique across 8 projects x 2 stages |
| Resource naming | `{project}-{stage}-{resource}` | Unique in shared account |
| Cross-project refs | SSM Parameter Store | Avoids CF ImportValue lock-in |
| Intra-project refs | CF exports (CDK-managed) | CDK handles ordering within a project |
| CRM IaC | CDK (two-stack pattern like health-web) | Standardizes on CDK for all app-layer projects |
| Deployments | Fresh to shared accounts | Old hwh-work deployments disregarded |
| Branch strategy | IaC: dev+main with promotion; Library: main only | dev->staging, main->prod |

### SSM Parameter Store Pattern

woxom-infra writes shared infrastructure values to SSM after deployment:
```
/woxom/{stage}/infra/UserPoolId
/woxom/{stage}/infra/UserPoolArn
/woxom/{stage}/infra/CognitoIssuerUrl
/woxom/{stage}/infra/{Product}ClientId   (one per product)
/woxom/{stage}/infra/EmailIdentityArn
```

Consuming CDK stacks read at synth time:
```typescript
const poolId = ssm.StringParameter.valueFromLookup(this, `/woxom/${stage}/infra/UserPoolId`);
```

## Status Summary

| Repo | Code | Tests | CI/CD | Auth | Staging | GitHub Issues |
|------|------|-------|-------|------|---------|---------------|
| woxom-infra | BUILT | None | Pipeline written | N/A | No | [6 issues](https://github.com/Augmenting-Integrations/woxom-infra/issues) |
| woxom-common | BUILT | 89py + 72ts | Pipeline written | N/A | N/A | [3 issues](https://github.com/Augmenting-Integrations/woxom-common/issues) |
| woxom-quoting-tool | Extracted | 41 files | Exists | API keys | No | [6 issues](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues) |
| woxom-data-parser | Extracted | 1 file | Exists | Basic Auth | No | [7 issues](https://github.com/Augmenting-Integrations/woxom-data-parser/issues) |
| woxom-sales-dashboard | Extracted | 5 files | Exists | bcrypt JWT | No | [5 issues](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues) |
| woxom-health-web | Partial | 31 files | OIDC pipeline | Cognito | Live (demo) | [5 new issues](https://github.com/Augmenting-Integrations/woxom-health-web/issues) |
| woxom-crm | Frontend only | 3 files | Exists | None | No | [6 issues](https://github.com/Augmenting-Integrations/woxom-crm/issues) |
| woxom-visualization | Extracted | 1 e2e | None | N/A | No | [2 issues](https://github.com/Augmenting-Integrations/woxom-visualization/issues) |

## Critical Path

```
Phase 0 (foundation)
  Push to GitHub ✅
  Create dev branches ✅
  CDK bootstrap shared staging account
  OIDC setup per repo

Phase 1 (shared infrastructure) ──> blocks all products
  woxom-infra: #1 naming → #2 SSM params → #3 pipeline → #4 deploy identity → #5 deploy email

Phase 2 (shared library) ──> blocks auth migration
  woxom-common: #1 publish PyPI, #2 publish npm

Phase 3 (per-product staging) ──> all parallelizable after Phase 1
  woxom-quoting-tool:     #1 parameterize → #2 naming → #3 SSM Cognito → #4 pipeline
  woxom-data-parser:      #1 parameterize → #2 naming → #3 pyproject → #4 SSM → #5 pipeline
  woxom-sales-dashboard:  #1 parameterize → #2 naming → #3 SSM → #4 pipeline
  woxom-health-web:       #4 rename stacks → #5 shared Cognito → #7 deploy (blocked by demo)
  woxom-crm:              #1 scaffold CDK → #2 infra → #3 Vite migration → #4 pipeline → #5 deploy
```

---

## Phase 0: Foundation -- DONE

- [x] Push all repos to GitHub (Augmenting-Integrations org)
- [x] Create dev branches for 6 IaC repos
- [x] Align health-web main/migrate/dev branches
- [ ] CDK bootstrap shared staging account (`AWS_PROFILE=woxom-eco-staging npx cdk bootstrap`)
- [ ] Create OIDC provider in staging account
- [ ] Create per-repo pipeline execution roles (see OIDC section below)

### OIDC Roles (Staging)

| Role | Trust | Repo |
|------|-------|------|
| `woxom-staging-infra-deploy` | `refs/heads/dev` | woxom-infra |
| `woxom-staging-quoting-tool-deploy` | `refs/heads/dev` | woxom-quoting-tool |
| `woxom-staging-data-parser-deploy` | `refs/heads/dev` | woxom-data-parser |
| `woxom-staging-sales-dashboard-deploy` | `refs/heads/dev` | woxom-sales-dashboard |
| `woxom-staging-health-web-deploy` | `refs/heads/dev` | woxom-health-web |
| `woxom-staging-crm-deploy` | `refs/heads/dev` | woxom-crm |

---

## Phase 1: Shared Infrastructure (woxom-infra)

Must deploy first -- provides Cognito and SES that all products depend on.

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-infra/issues/1) Adapt SAM templates for shared account naming
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-infra/issues/2) Add SSM parameter outputs for Cognito/SES
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-infra/issues/3) Create OIDC pipeline (dev->staging, main->prod)
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-infra/issues/4) Deploy identity stack to staging
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-infra/issues/5) Deploy email stack to staging
- [ ] [#6](https://github.com/Augmenting-Integrations/woxom-infra/issues/6) Standardize repo

---

## Phase 2: Shared Library (woxom-common)

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-common/issues/1) Publish Python package to PyPI
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-common/issues/2) Publish Node package to npm
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-common/issues/3) Standardize repo

---

## Phase 3: Per-Product Staging Deployment

### woxom-quoting-tool

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/1) Parameterize CDK with stage context
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/2) Standardize resource/export naming
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/3) Read shared Cognito from SSM
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/4) Update pipeline to OIDC + dual-env
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/5) Rename legacy HWH references
- [ ] [#6](https://github.com/Augmenting-Integrations/woxom-quoting-tool/issues/6) Standardize repo

### woxom-data-parser

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/1) Parameterize CDK with stage context
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/2) Standardize resource/export naming
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/3) Convert requirements.txt to pyproject.toml
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/4) Read shared Cognito from SSM
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/5) Update pipeline to OIDC + dual-env
- [ ] [#6](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/6) Rename legacy e123/E123 references
- [ ] [#7](https://github.com/Augmenting-Integrations/woxom-data-parser/issues/7) Standardize repo

### woxom-sales-dashboard

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues/1) Parameterize CDK with stage context
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues/2) Standardize resource/export naming
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues/3) Read shared Cognito from SSM
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues/4) Update pipeline to OIDC + dual-env
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-sales-dashboard/issues/5) Standardize repo

### woxom-health-web

**Note**: Staging is live for a demo. Stack rename and Cognito migration deferred until demo completes.

- [ ] [#6](https://github.com/Augmenting-Integrations/woxom-health-web/issues/6) Ensure dev branch aligned
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-health-web/issues/4) Rename stack prefixes for shared account (after demo)
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-health-web/issues/5) Point Cognito to shared pool from woxom-infra (after demo)
- [ ] [#7](https://github.com/Augmenting-Integrations/woxom-health-web/issues/7) Deploy to shared staging account
- [ ] [#8](https://github.com/Augmenting-Integrations/woxom-health-web/issues/8) Standardize repo

### woxom-crm (Greenfield)

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-crm/issues/1) Scaffold CDK project (two-stack pattern)
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-crm/issues/2) Create basic infrastructure (DynamoDB, API, Lambda, CloudFront)
- [ ] [#3](https://github.com/Augmenting-Integrations/woxom-crm/issues/3) Migrate frontend from Next.js to Vite SPA
- [ ] [#4](https://github.com/Augmenting-Integrations/woxom-crm/issues/4) Create OIDC pipeline
- [ ] [#5](https://github.com/Augmenting-Integrations/woxom-crm/issues/5) Deploy skeleton to staging
- [ ] [#6](https://github.com/Augmenting-Integrations/woxom-crm/issues/6) Standardize repo

### woxom-visualization (Low Priority)

- [ ] [#1](https://github.com/Augmenting-Integrations/woxom-visualization/issues/1) Add basic CI pipeline
- [ ] [#2](https://github.com/Augmenting-Integrations/woxom-visualization/issues/2) Standardize repo

---

## Phase 4: Polish and Hardening

**Rename sweep (all repos):**
- [ ] Systematic HWH/e123 rename across all products
- [ ] `INST#hwh` DynamoDB partition key migration in sales-dashboard (high-risk, needs migration script + rollback plan)

**Domains:**
- [ ] Production: `*.woxomhealth.com` custom domains for all products
- [ ] Staging: `*.aillc.link` for all staging environments
- [ ] ACM certificates + DNS records

**Cross-product integration:**
- [ ] Cognito integration test: single user authenticates to all 5 products
- [ ] SES consolidation: decide if quoting-tool keeps its own SES stack or moves to woxom-infra

**Standardization (all repos):**
- [ ] Pre-commit hooks: ruff/mypy (Python), eslint/prettier (Node)
- [ ] Renovate dependency update configs
- [ ] Semantic-release conventional commit enforcement
- [ ] OpenAPI specs for all API products (quoting-tool, data-parser, sales-dashboard, crm)
- [ ] Enforce `--cov-fail-under=80` in all CI pipelines

**Observability (all deployed products):**
- [ ] Structured JSON logging
- [ ] X-Ray tracing
- [ ] CloudWatch dashboards per product
- [ ] SNS alarm notifications to admin@woxomhealth.com

---

## Per-Repo Quick Reference

| Repo | IaC | Language | Deploy Pattern |
|------|-----|----------|----------------|
| woxom-common | None (library) | Python + TypeScript | Publish to PyPI + npm |
| woxom-infra | SAM (no CDK) | Python (Lambda) | sam deploy (staging/prod) |
| woxom-crm | CDK (2 stacks) | TypeScript (Lambda + React) | CDK deploy (staging/prod) |
| woxom-data-parser | CDK (2 stacks) | Python (Flask/Mangum) | CDK deploy (staging/prod) |
| woxom-quoting-tool | CDK (5 stacks) | JavaScript/Node.js | CDK deploy (staging/prod) |
| woxom-sales-dashboard | CDK (6 stacks) | Python (FastAPI) + React | CDK deploy (staging/prod) |
| woxom-health-web | CDK (2 stacks) | TypeScript (React + Lambda) | CDK deploy (staging/prod) |
| woxom-visualization | None (dev tool) | TypeScript (React/Vite) | Optional S3/CloudFront |

## Key Files (Source of Truth)

| What | Where | Notes |
|------|-------|-------|
| AV calculation | `woxom-common/python/src/woxom_common/av.py` | Canonical. Node version must match. |
| Agent types | `woxom-common/python/src/woxom_common/agents.py` | 57 agents, Direct vs Independent |
| Agent merges | `woxom-common/agent-merges.json` | Shared by both Python and Node |
| Cognito JWT middleware | `woxom-common/python/src/woxom_common/auth/cognito.py` | Lambda authorizer pattern |
| Cognito User Pool | `woxom-infra/identity/template.yaml` | All products validate against this |
| SES email | `woxom-infra/email/template.yaml` | Cross-account sending |
| CRM DynamoDB schema | `woxom-crm/docs/dynamodb-data-model.md` | 2 tables, 8 GSIs |
| CRM implementation plan | `woxom-crm/IMPLEMENTATION_PLAN.md` | 20 modules, 25 weeks |
| Reference authorizer | `reference/hwh-work/reference-repos/ai-lls-api/src/auth_authorizer.py` | Ported to woxom-common |
| Gold-standard pipeline | `woxom-health-web/.github/workflows/pipeline.yaml` | OIDC, staging/prod, E2E |

## Workflow

**Root session** (woxom-ecosystem): Planning, ticket creation, progress monitoring via `gh`.

**Per-submodule sessions**: `ai-shell claude` from submodule root. Gets proper `.env`, CLAUDE.md. Works tickets with standard skills (ai-prepare-branch, ai-submit-work, ai-monitor-pipeline).

**GitHub Issues** are the coordination mechanism. Tickets include blocked-by references.
