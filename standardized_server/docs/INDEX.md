# Documentation Index

This documentation is organized by reader intent. Use this page as the map for
the reference server.

## Start Here

| Document | Use it when you want to know |
| --- | --- |
| [Product Overview](PRODUCT.md) | What the project is, who it is for, and what problem it solves. |
| [Quickstart](QUICKSTART.md) | How to install, configure, run, and smoke-test the server. |
| [Architecture](ARCHITECTURE.md) | How the runtime, modules, proxy services, workflow, and stores fit together. |
| [Complete System Flow and Rendering Architecture](SYSTEM_FLOW_REPORT.md) | How React, Node, Gemini, Python, memory, artifacts, and UI renderers work end to end. |
| [Codebase Tour](CODEBASE_TOUR.md) | Where code lives and what each file or package owns. |
| [React User Interface](UI.md) | How to run and understand the conversational React and LLM gateway. |

## Implementation Reference

| Document | Use it when you want to know |
| --- | --- |
| [Tool Contract](TOOL_CONTRACT.md) | Which MCP tools exist and how they map to OGC concepts. |
| [Proxy Workflow](PROXY_WORKFLOW.md) | How process execution is planned, resolved, confirmed, and executed. |
| [Process Output Artifacts](OUTPUT_ARTIFACTS.md) | How inline and referenced outputs are resolved, interpreted, stored, and presented. |
| [Configuration](CONFIGURATION.md) | How to configure servers, defaults, auth, security, limits, stores, and policy. |
| [Security Model](SECURITY.md) | Which boundaries protect credentials, upstream targets, references, and execution. |
| [Development Guide](DEVELOPMENT.md) | How to work on the implementation safely. |
| [Testing Guide](TESTING.md) | What the test suite covers and how to run it. |
| [Deployment Guide](DEPLOYMENT.md) | How to think about stdio, Streamable HTTP, Redis, and production controls. |
| [Extending the Server](EXTENDING.md) | How to add new OGC API modules or tools. |
| [Troubleshooting](TROUBLESHOOTING.md) | Common setup, config, transport, auth, and workflow problems. |
| [Conformance Checklist](CONFORMANCE.md) | Experimental behavior expected from compatible implementations. |

## Project and Review Material

| Document | Use it when you want to know |
| --- | --- |
| [GSoC Final Report](gsoc/FINAL_REPORT.md) | The project story, implemented work, limitations, and next steps. |
| [GSoC Deliverables](gsoc/DELIVERABLES.md) | What was delivered and where each artifact lives. |
| [GSoC Timeline](gsoc/TIMELINE.md) | A chronological view of the work. |
| [Architecture Decision Records](adr/) | Important design decisions and their rationale. |
| [UML Diagrams](uml/README.md) | Component, class, and process-execution diagrams. |

## Source Artifacts

| Artifact | Purpose |
| --- | --- |
| [`../spec/ogc-mcp-tool-contract.json`](../spec/ogc-mcp-tool-contract.json) | Experimental tool contract implemented by this server. |
| [`../../spec/ogc-mcp-mapping.json`](../../spec/ogc-mcp-mapping.json) | Early mapping specification for OGC APIs to MCP concepts. |
| [`../../spec/ogc-output-manifest.schema.json`](../../spec/ogc-output-manifest.schema.json) | Versioned contract for execution, retrieval, interpretation, and presentation state. |
| [`../../spec/ogc-workflow-event.schema.json`](../../spec/ogc-workflow-event.schema.json) | Ordered activity and background-workflow event contract. |
| [`../../spec/ogc-clarification-request.schema.json`](../../spec/ogc-clarification-request.schema.json) | Structured human-in-the-loop ambiguity contract. |
| [`../schemas/server-config.schema.json`](../schemas/server-config.schema.json) | JSON Schema for operator configuration files. |
| [`../config.example.json`](../config.example.json) | Example server configuration. |
