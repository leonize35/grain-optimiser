# UI component library — specification

## Principles
Use a small shared component system with consistent labels, spacing, contrast, keyboard support and form validation. Follow `UI_UX_SCREENS.md`. Do not turn every status into a coloured badge; reserve prominent colour for actionable exceptions.

## Global components
- `AppShell`: responsive sidebar/header/main content with skip-navigation link.
- `SiloSwitcher`: searchable list showing approved current silo and configuration status.
- `PageHeader`: page title, concise description and one dominant action.
- `ModelAssuranceIndicator`: verification/validation scope and last check date; never simply 'Verified' for a calibrated-only model.
- `NotificationCentre`: errors, warnings and updates, with accessible announcements.
- `EmptyState`, `LoadingState`, `ErrorState`: contextual message and recovery action.
- `UnsavedChangesGuard`: prompts when leaving an edited draft.

## Configuration components
- `EquipmentPalette`: resource types with operational names and icons.
- `FacilityGraphCanvas`: zoom/pan, add/select nodes, explicit directed truck/grain edges; accessible list/table alternative to visual graph.
- `ResourcePropertiesPanel`: capacities, units, commodity assignment, schedule; inline validation.
- `ConnectionEditor`: from/to ports, direction, type, capacity, changeover and permitted commodity rules.
- `ConnectivityCheckList`: reachability errors, invalid types, missing bin destinations and next steps.
- `OperatingRulesForm`: policy selector + help text for FIFO vs feasible-first vs batching; explicit fallback when no request feasible.

## Data and scenario components
- `DataUploadWizard`: file upload, column mapping, sample preview, data-quality status, match report.
- `AssumptionTag`: measured / imported / estimated / manager-entered; with data source and freshness.
- `ScenarioGoalPicker`: queues, turnaround, throughput, capacity.
- `ScenarioChangeEditor`: resource change and demand profile controls.
- `ScenarioDiff`: side-by-side baseline vs proposed parameter modifications.
- `PreflightResults`: grouped blocking errors and nonblocking warnings with links to fix locations.

## Execution and result components
- `RunStatusPanel`: server-sourced state, job ID, replications complete/total, timestamp, logs and cancel. No simulated progress percentages.
- `KpiCard`: metric, units, comparison delta, baseline name, confidence interval when available.
- `ScenarioComparisonTable`: baseline, demand-only, proposed under equal-demand conditions.
- `DistributionChart`: turnaround/queue distributions with percentile explanation and accessible data table.
- `ResourceUtilisationView`: utilisation and blocked/starved/busy time; avoid declaring a bottleneck from utilisation alone.
- `InsightsPanel`: grounded explanations with uncertainty and validation note; no invented causal claims.
- `ExportPanel`: scope, inputs, reproducibility metadata and output format.

## Design tokens — proposed, confirm with user
- Background: #F7F9FA; Surface: #FFFFFF; Primary navigation: #11293F; Primary action: #155DB5.
- Primary text: #182736; Secondary: #526375; Border: #DEE5EB.
- Positive: #236A50; Warning: #9D681B; Error: #B23839.
- Spacing steps: 4, 8, 12, 16, 24, 32 px. Corner radii: 8, 12 px. Typography: readable sans-serif, 16 px baseline.
- WCAG-compliant contrast must be verified; colour alone must never convey meaning.
- These are illustrative tokens, not a final brand mandate. Avoid invented customer/company branding in production designs.

## Critical interactions
1. New hopper added with no connections → `ConnectionEditor` highlights incomplete physical path; `PreflightResults` blocks run.
2. Shared elevator selected → resource utilisation describes shared capacity and contention without duplicating throughput.
3. Scenario edits +20% arrivals → comparison summary explicitly says baseline, demand-only, demand-plus-hopper.
4. Run starts → configuration snapshot freezes; changing settings creates a new revision.
5. Failed run → diagnostics view provides recovery path; cannot show partial metrics as complete.
6. Validation data missing → results labelled exploratory and cannot imply investment readiness.

## Acceptance criteria
- No frontend source-code changes needed to draw a second supported facility topology.
- Keyboard operability for forms and alternative access to the facility graph.
- Responsive at desktop and tablet sizes; mobile at least supports results and reports.
- Every input has label, units, default provenance and clear error message.
- Every result is labelled as real, simulated or placeholder.
