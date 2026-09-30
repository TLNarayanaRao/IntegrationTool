# Control Plane operations workspace

Open **Applications** to manage deployments or uploaded packages. Existing configuration, starter controls, logs, revision history, and health information remain available through **Manage** on an application card.

## Views and finding applications

- **Cards** shows application identity, environment, owning team, instance state, and reported health.
- **Compact** provides denser application cards.
- **Status board** groups deployments by lifecycle state. It is not a drag-to-deploy board: state changes require explicit lifecycle actions.
- Combine search, lifecycle state, data plane, environment, and team filters. **Needs attention** selects failed deployments or unhealthy/degraded health reports.
- Star applications and enable **Favorites** to focus on them. Favorites and view preferences are stored locally in this browser, not shared with other operators.
- **Ctrl+K** (Command+K on macOS) opens application search, unless a dialog is open.

## Bulk lifecycle operations

Select individual deployments or **Select visible**, then choose **Start**, **Stop**, or **Restart**. Only eligible selected deployments are included in the confirmation dialog. Review the names, environments, and teams before confirming. Stop/restart may interrupt processing.

The client re-fetches each deployment before sending its operation, executes requests sequentially, and reports accepted, skipped, or failed results separately. A failure does not prevent later targets from being attempted. Accepted requests are not proof of healthy execution; inspect updated deployment status and health. Closing the result dialog does not cancel requests already sent. Changing filters clears hidden selections. There is deliberately no bulk delete.

UI eligibility follows the Technology Team/Application Manager model. Every request still uses the existing authenticated API and server-side authorization; client-side controls do not grant permissions.

## Themes

Use **Theme** in the top header: **Ocean dark**, **Slate dark**, **Light**, or **System**. System follows the operating system preference. The choice persists locally per browser origin and applies to navigation, forms, dialogs, application views, and telemetry surfaces. Windows desktop and browser clients use the same served UI; their local preferences may differ.

## Updating an installation

Deploy the updated `administrator/web` assets together, including `index.html`, `operations-workspace.js`, and `operations-workspace.css`. Refresh the browser or reload the Windows Control Plane client. No database migration is required. Do not replace your existing administrator data directory, environment settings, or credentials.
