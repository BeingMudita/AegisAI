# AegisAI workspace

React + TypeScript + Vite + Tailwind + Recharts. Existing backend security controls
remain authoritative; the client presents their decisions and evidence.

```bash
npm install
npm run dev        # localhost:5173; API proxy defaults to localhost:8000
npm run build      # type-check and production build
```

Use `AEGIS_API_TARGET` in the shell or frontend `.env` to change the development
proxy destination. Use `VITE_API_URL` for a separately hosted production API.
Development account shortcuts are excluded from production builds.

## User flow

Overview → Knowledge base → Agent workspace → Security events (staff), with
Architecture available throughout to explain components and security boundaries.
Examples fill a draft; sending is an explicit action.

| Page | Access | Purpose |
|---|---|---|
| Overview | All authenticated users | Guided starting point, role-aware metrics, agent readiness; staff analytics and recent incidents |
| Agent workspace | All authenticated users | Guarded chat, actual stage progress, session history/recovery, evidence export |
| Architecture | All authenticated users | Clickable component graph, highlighted flows, implementation details and section links |
| Knowledge base | Existing role controls | Upload/import/paste (admin), ingestion progress, documents and search; quarantine/source inspection (staff) |
| Firewall lab | All authenticated users | Text/channel scan and editable presets; rule list for staff |
| Security events | Staff | Live filters, expandable evidence, JSON export of at most 200 matching events |
| Trust | Staff | Trust histories; administrator overrides |
| Policies & tools | Existing role controls | Per-agent policies, tool registry, gateway evidence |

## Design and reliability

- Light theme by default, with dark and system options. Preferences are validated.
- Restrained teal controls, quiet surfaces, readable contrast, and consistent spacing.
  Decision charts retain distinct blue/red series plus labels and table alternatives.
- Responsive navigation with Escape, keyboard focus containment and restoration;
  skip link and labeled controls. Animations respect reduced-motion preferences.
- Diagram nodes are native buttons with pressed state and details relationships.
  A text connection list complements the graphic; narrow diagrams scroll locally.
- The mobile execution monitor opens above the conversation during a request.
  Server progress is polled every 400 ms; quick runs use the final trace.
- Polling requests do not overlap, stop on unmount, pause in hidden tabs, and time
  out after 15 seconds. Failed reads surface errors instead of silently clearing data.
- Pages load separately, with loading and error recovery states. Agent answers are
  rendered as React text, never injected HTML.
- Exports are JSON snapshots with timestamps. Conversation exports include messages
  and retrieved context; event exports record filters and the 200-event view limit.

See [CHANGELOG](../CHANGELOG.md), [operator guide](../docs/operator-guide.md), and
[architecture](../docs/architecture.md) for backend behavior and deployment limits.
