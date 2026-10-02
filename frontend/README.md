# AegisAI Dashboard

React 19 + TypeScript + Vite + Tailwind 4 + Recharts.

```bash
npm install
npm run dev        # http://localhost:5173 — /api is proxied to http://localhost:8000
npm run build      # type-check + production build into dist/
```

## Pages

| Page | Who | What |
|---|---|---|
| Overview | staff | Event / decision / trust charts, latest events, runtime info |
| Agent console | everyone | Chat with an agent; every turn shows its security trace, tool-call checkpoints and retrieved / dropped sources. Includes benign and attack examples. |
| Firewall lab | everyone | Scan any text on any channel; obfuscation presets; rule set (staff) |
| Trust | staff | Trust registry, per-subject history chart, admin override |
| Security events | staff | Filterable live audit log |
| Data & RAG | everyone | Live ingestion pipeline. Upload files (drag and drop) or import from the server folder (admin), watch jobs progress, browse and delete documents, test search, quarantine and per-source trust (staff) |
| Policies & tools | everyone | Agent policies; tool registry and gateway log (staff) |

Staff = `ADMIN` and `SECURITY_ANALYST`.

## Notes

- Colors are CSS tokens in `src/index.css` with separately chosen dark-mode
  steps; the theme follows the OS unless picked in the sidebar.
- Status is never color-only: badges pair an icon with a label, and every chart
  has a table view. The allowed/denied pair is blue/red (validated for color
  blindness; green/red is not).
- Agent answers are rendered as React elements (`RichText`), never as raw HTML.
- For a separately hosted API set `VITE_API_URL` (see `.env.example`).
