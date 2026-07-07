# GSoC Timeline

This timeline is organized by project phase rather than exact dates.

## Phase 1: Research And Scope

Focus:

- study OGC API modules relevant to the project;
- study MCP tool design patterns;
- identify useful bridges between natural-language clients and OGC APIs;
- decide that the reference implementation should prioritize Common, Features,
  Records, and Processes.

Outputs:

- initial project scope;
- early mapping concepts;
- first structure for the mapping specification.

## Phase 2: Mapping Specification

Focus:

- describe OGC API operations as MCP-style tools;
- define modules, HTTP mappings, input schemas, output summaries, and error
  handling concepts;
- keep the artifact language-agnostic.

Outputs:

- `spec/ogc-mcp-mapping.json`.

## Phase 3: Reference Server Foundation

Focus:

- create the Python package;
- add FastMCP server creation;
- add operator-owned configuration;
- add registry and bounded HTTP transport;
- implement Common, Features, Records, and Processes modules.

Outputs:

- package under `standardized_server/src/ogc_mcp_reference`;
- config example and schema;
- initial service tests.

## Phase 4: Safety And Human Confirmation

Focus:

- prevent arbitrary upstream targets;
- inject credentials outside model context;
- validate referenced process inputs;
- design the proxy plan lifecycle;
- require explicit human approval before execution.

Outputs:

- `ProxyPlanner`;
- `PlanningWorkflow`;
- process execution confirmation gate;
- policy-gated direct execution.

## Phase 5: Large Payload Handling

Focus:

- avoid copying large OGC responses into model context;
- summarize model-facing data;
- store full payloads behind opaque handles;
- support pagination over stored payloads.

Outputs:

- `ResponseSanitizer`;
- `ProxyMemoryStore`;
- `response_mode` support;
- memory retrieval tools.

## Phase 6: State Persistence And Deployment Readiness

Focus:

- separate state storage from planner and memory logic;
- support single-worker local operation;
- support shared external state for multi-worker deployments;
- document Redis use.

Outputs:

- `KeyValueStore`;
- `InMemoryStore`;
- `RedisStore`;
- Redis config example;
- store tests.

## Phase 7: Testing, Hardening, And Documentation

Focus:

- cover critical behavior with deterministic tests;
- write architecture and conformance documentation;
- document configuration, security, deployment, and extension paths;
- prepare GSoC review material.

Outputs:

- unittest suite;
- technical docs under `standardized_server/docs`;
- GSoC final report and deliverables map.

## Future Work

Potential future phases:

- user/session-scoped plan and memory isolation;
- DNS-aware SSRF protection;
- dedicated tools for more OGC API modules;
- stronger interoperability test suite;
- broader review of the experimental tool contract.
