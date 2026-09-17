# Control Plane operator workspace

The Control Plane home page summarizes running applications, data-plane
connectivity, unhealthy/stopped deployments, and recent operations. The
**Applications** workspace lets an operator search and filter deployments and
packages, then inspect an application without leaving the list.

The application inspector exposes lifecycle actions, health and instances,
environment/instance/health-check configuration, write-only secret updates,
Starter Task controls, runtime logs, revision history and revert, configuration
comparison, backup, and restore. Existing package upload, archive inspection,
and deployment flows remain available.

The **Telemetry** page shows CPU, memory, and disk readings reported by agents,
with bounded trends (up to 720 samples per data plane, sampled no more than
once every 15 seconds). It also shows task outcomes and recent Control Plane
request errors. Blank readings mean the agent has not reported that metric;
they are not treated as zero.

Operators can create or delete alert rules for offline data planes, failed
deployments, unhealthy applications, and CPU/memory/disk thresholds. Resource
rules report `NO_DATA` when a host has not sent the selected metric. Rules are
evaluated in the Control Plane UI/API; external notification delivery is not
implemented by these rules.

Python data-plane agents install `psutil` to report host CPU, memory, and disk.
If `psutil` is unavailable, the agent still reports disk space and its local
process count. A remote on-premises Python agent forwards a bounded tail of
each instance log. Kubernetes pod-log forwarding is not yet implemented;
local deployments are read from the Control Plane host.
