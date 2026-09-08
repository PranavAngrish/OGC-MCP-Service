# UML Diagrams

PlantUML source files in this folder document the reference server from three
viewpoints.

| Diagram | Purpose |
| --- | --- |
| `system-architecture.puml` | Full-stack component view: React UI, Node/Gemini gateway, the Python FastMCP server's runtime services, and registered OGC API deployments. |
| `internal-classes.puml` | Major Python classes and dependencies, including the proxy planner/workflow and the output-artifact pipeline. |
| `process-execution-sequence.puml` | Discovery, planning, confirmation, and execution flow. |

Render with PlantUML:

```bash
plantuml standardized_server/docs/uml/*.puml
```

The diagrams are documentation aids. The source code and tests remain the source
of truth.
