# Relay — modules, functionality, and the screens they need

ITIL 4 vocabulary throughout: *change enablement* (not change management),
*service request*, *problem* with its *known error*, *configuration item*.

## Requester side — the single point of contact

| Module | Functionality | Screen |
|---|---|---|
| Intake | One front door for every kind of ask; no "which form" maze | `/` one-box intake |
| Request tracking | Status, SLA promise, thread, reopen | `/my` my requests |
| Service catalog | Browse offered services, per-service forms | `/catalog` |
| Self-help | KB search, guided fixes before a ticket exists | inline in intake |
| Approvals | Approve/reject what is waiting on you | `/approvals` |

## Agent side — the workbench

| Module | Functionality | Screen |
|---|---|---|
| Queue | Unified inbox, saved views, filters, bulk actions, SLA-risk sort | `/queue` |
| Ticket work | Conversation (public vs internal), properties, tasks, SLA, related, activity | `/t/:id` |
| Incident | Classify, route, diagnose, resolve, link to problem | same workbench |
| Service request | Catalog-driven, task checklist, approval gates | same workbench |
| Problem | Root cause, known error, workaround, linked incidents | `/problems` |
| Change enablement | Risk, schedule, collision detection, CAB approval, calendar | `/changes` |
| Knowledge | Author, review, publish, usage stats | `/kb` |
| CMDB | CIs, dependencies, blast-radius view | `/cmdb` *(stub)* |

## Oversight

| Module | Functionality | Screen |
|---|---|---|
| Queue health | SLA attainment, MTTR, backlog age, first-contact resolution, CSAT | `/insights` |
| Configuration | Priority matrix, SLA targets, categories, teams, routing rules, catalog items | `/admin/*` |

## The four practices the prototype does not carry

Release & deployment, asset & licence management, purchasing & contracts,
availability/capacity planning. Linkable by id, not designed.
