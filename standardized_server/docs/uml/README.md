# UML Diagrams

PlantUML source files in this folder document the reference server from three
viewpoints.

| Diagram | Purpose |
| --- | --- |
| `system-architecture.puml` | Component and deployment-level architecture. |
| `internal-classes.puml` | Major Python classes and dependencies. |
| `process-execution-sequence.puml` | Discovery, planning, confirmation, and execution flow. |

Render with PlantUML:

```bash
plantuml standardized_server/docs/uml/*.puml
```

The diagrams are documentation aids. The source code and tests remain the source
of truth.
