# UI / UX screen specification for the Silo Decision Platform

## Purpose
This document captures the intended **manager-facing product experience** so that future design and engineering work stays aligned with the product vision. The user is typically a **silo manager or operations lead**, not a simulation specialist. The interface must therefore expose powerful simulation capability through a simple, guided workflow.

## Product design principles
1. **Speak the manager's language.** Use terms like *queue*, *truck turnaround time*, *hopper*, *elevator*, *bin*, *throughput*, *scenario*, not simulation jargon.
2. **One clear next step per screen.** Each screen should have one dominant call to action.
3. **Progressive disclosure.** Default mode stays simple; advanced technical detail is available on demand.
4. **Show cause and effect.** Users must always be able to see what changed, why it changed, and what outcome it had.
5. **Prevent invalid setups.** The system should validate configurations before a run and explain errors clearly.
6. **Comparison is the core value.** The UI must make it very easy to compare baseline vs proposed changes.
7. **Never hide model limits.** Assumptions, warnings, missing data and validation scope must remain visible.
8. **Make state obvious.** The user should always know whether the model is draft, valid, queued, running, complete or failed.
9. **Optimise for decisions, not animation.** The tool is for operational and capital decisions; visuals should support interpretation, not show off complexity.
10. **Design for infrequent users.** A manager may only use the tool before harvest or when planning improvements, so the flow must be intuitive without retraining.

## Primary workflow
The manager-facing journey should follow this flow:

1. **My Silo / Dashboard**
2. **Configure Silo**
3. **Operating Rules**
4. **Import / Review Data**
5. **Create Scenario**
6. **Validate Configuration**
7. **Run Simulation**
8. **Compare Results**
9. **Inspect Diagnostics / Utilisation**
10. **Export Report**

This is more important than exposing the internal engine structure.

## Global layout pattern
The product should use a clean web-application layout:

- **Left navigation rail** with icons + labels for the main sections.
- **Top header bar** with page title, silo selector, scenario selector, run status badge and user menu.
- **Main content area** with cards, charts, forms and tables.
- **Right-side optional insight panel** on complex screens for assumptions, warnings or contextual help.
- **Sticky action bar** on configuration screens with actions such as Save Draft, Validate, Run, Compare.

## Design language
- Clean, modern, professional look.
- White or light neutral background.
- Accent colour: green/teal family fits the agriculture and operations context.
- Use badges for states: Draft, Valid, Warning, Running, Failed, Completed.
- Use cards with strong headings and short explanatory text.
- Use charts only where they add interpretation value.
- Use icons sparingly and consistently.

## Screen specifications

### 1. Dashboard / My Silo
**Purpose:** give the manager an immediate summary of the configured silo and recent model results.

**Main panels:**
- Silo summary card: site name, configuration version, validation status.
- KPI cards: median turnaround time, average queue length, throughput, hopper wait.
- Recent runs table: scenario, date, status, user, result summary.
- Alerts / issues panel: incomplete configuration, stale data, validation warnings.
- Quick actions: Configure silo, Test a change, Upload data.

**Primary CTA:** `Test a Change`

### 2. Silo Configuration
**Purpose:** configure the physical network in a user-friendly way.

**Main panels:**
- Visual network canvas showing receiving hoppers, conveyors, elevator legs, bins and weighbridges.
- Left component library / equipment palette.
- Selected equipment properties panel.
- Connectivity checker panel.

**Key interactions:**
- Add/edit/remove equipment.
- Draw or edit allowed connections.
- Set equipment capacity, speed and availability.
- Mark whether a hopper serves receiving, dispatch or both.
- Highlight unreachable bins or invalid paths.

**Primary CTA:** `Validate Configuration`

### 3. Operating Rules
**Purpose:** configure how the silo is run, not only what equipment exists.

**Main sections:**
- Truck sequencing policy: FIFO, feasible-first, batch/commodity grouping.
- Changeover rules: commodity restrictions, setup time.
- Resource allocation rules: operators, weighbridges, shared equipment priorities.
- Dispatch scheduling: booked windows, priorities.
- Storage rules: bin compatibility, fill constraints.

**Primary CTA:** `Save Rules`

### 4. Data Import and Review
**Purpose:** bring in site-specific operating data and show what is usable.

**Main panels:**
- Upload area for ERP exports and manual templates.
- Mapping/preview table.
- Data quality summary: matched rows, missing values, excluded records.
- Distribution summary cards: arrivals, load sizes, unloading times, commodity mix.

**Primary CTA:** `Use in Scenario`

### 5. Scenario Setup
**Purpose:** define the baseline and proposed change in plain business language.

**Main sections:**
- Goal selector: queues, turnaround time, throughput, utilisation, weighbridge congestion.
- Proposed change selector: add hopper, add elevator leg, increase staff, change queue rule, cap unload time, etc.
- Demand change controls: increase arrivals %, seasonal pattern, opening backlog.
- Scenario summary card: what is changing relative to baseline.
- Assumption panel.

**Primary CTA:** `Validate & Run`

### 6. Validation Screen / Pre-run Check
**Purpose:** stop bad scenarios before compute time is wasted.

**Checks shown:**
- Missing required equipment connections.
- Invalid bin or hopper routing.
- Inconsistent capacities.
- Missing input distributions or schedules.
- Impossible dispatch/load combinations.
- Warning-level checks such as limited validation data.

**Output format:**
- Pass/fail banner.
- Checklist grouped by Errors, Warnings, Notes.
- Each issue should say what is wrong, where it is, and how to fix it.

**Primary CTA:** `Run Simulation` (only enabled on pass; allowed with warnings by confirmation)

### 7. Run Simulation
**Purpose:** show run progress clearly and support asynchronous jobs.

**Main panels:**
- Run status header: Queued / Starting / Running / Aggregating / Completed / Failed.
- Progress bar.
- Replications completed / remaining.
- Runtime estimate.
- Engine version, config hash, random seed policy.
- Live log/diagnostics panel.

**Key requirement:** user can leave the page and return later; the run continues in the background.

**Primary CTA:** `View Results` when complete.

### 8. Compare Results
**Purpose:** this is the product's main value screen.

**Main panels:**
- Baseline vs scenario summary table.
- KPI comparison cards with deltas.
- Charts with distributions, not just averages.
- Confidence / uncertainty panel.
- Recommendation support block: whether the scenario improved the selected goal.
- Explicit note that business value assumptions must be interpreted by management.

**Key comparisons:**
- Turnaround time.
- Queue length and queue time.
- Throughput.
- Hopper wait.
- Weigh-only impact.
- Equipment utilisation.

**Primary CTA:** `Inspect Bottlenecks` or `Export Report`

### 9. Resource Utilisation / Diagnostics
**Purpose:** help the manager understand *why* a result occurred.

**Main panels:**
- Resource utilisation heatmap or card list.
- Bottleneck ranking.
- Time-in-state charts.
- Queue build-up by hour.
- Route blockage / connectivity explanation.
- Diagnostic warnings from invariants.

**Primary CTA:** `Adjust Scenario`

### 10. Reports / Export
**Purpose:** produce a management-ready output.

**Main sections:**
- Executive summary.
- Scenario definition.
- Key results.
- Bottleneck explanation.
- Validation and assumptions.
- Appendices with technical detail.

**Export formats:** PDF, PowerPoint-ready summary, CSV for key result tables.

## MVP screen priority
The most important screens to build first are:
1. **Silo Configuration**
2. **Scenario Setup**
3. **Validation Screen**
4. **Run Simulation**
5. **Compare Results**

These prove the core commercial value: configure a silo, test a change, run a scenario and interpret the outcome.

## Recommended navigation labels
- Dashboard
- My Silo
- Operating Rules
- Data
- Scenarios
- Runs
- Results
- Reports
- Settings

## Important UX constraints for implementation
- Do not expose raw simulation objects or event scheduler internals in default mode.
- Default to **guided forms**, not freeform technical entry.
- Allow advanced users to expand technical sections.
- Preserve an audit trail of who changed what and when.
- Always show the selected baseline and scenario.
- Always show if a run is based on stale data or an unvalidated configuration.

## Suggested first clickable prototype
Before building the full front end, a clickable prototype should cover:
- Dashboard
- Silo Configuration
- Scenario Setup
- Run Simulation
- Compare Results

The prototype does not need a working engine yet, but must make the workflow clear enough for stakeholder feedback and pilot sales discussions.
