# Product Overview

## Status

This project is an experimental reference implementation created during a GSoC
2026 project with 52North. It explores how the Model Context Protocol can expose
OGC API capabilities to AI clients through a stable, auditable tool contract.

It is not an adopted OGC Standard.

## Problem

OGC APIs are powerful but specialized. A user who asks for geospatial data or
analysis often does not know:

- which OGC API module is relevant;
- which server hosts the needed collections or processes;
- which process ID to use;
- which input names and schemas the upstream server requires;
- whether execution is synchronous or asynchronous;
- how to keep large geospatial payloads out of an LLM context window;
- how to avoid leaking credentials or sending requests to unapproved hosts.

The reference server addresses those problems by putting a strict, typed MCP
tool surface in front of operator-approved OGC API deployments.

## Product Goal

The server is a bridge between:

- AI clients that speak MCP and can call named tools; and
- OGC API deployments that expose Common, Features, Records, and Processes
  endpoints over HTTP.

The bridge gives the client enough structure to discover capabilities, inspect
data, prepare process requests, and execute work only after explicit human
approval.

## Primary Users

- Researchers and engineers evaluating MCP as an interface for geospatial APIs.
- OGC API implementers who want a concrete reference pattern for tool design.
- Application engineers integrating AI clients with registered geospatial
  services.
- Reviewers of the GSoC project who need to understand the deliverables and the
  engineering choices.

## What The Server Does

The server:

- lists operator-approved OGC API servers;
- discovers landing pages and conformance documents;
- lists and retrieves OGC API - Features collections and items;
- lists and searches OGC API - Records catalogues;
- lists, describes, executes, and follows OGC API - Processes jobs;
- creates stored execution plans before running processes;
- validates process IDs, declared sources, and simple execute-input issues;
- requires explicit human confirmation before proxy execution;
- stores large responses behind proxy memory handles;
- sanitizes model-facing summaries;
- injects credentials from environment variables outside model-visible tool
  arguments;
- enforces response size limits, request timeouts, relative paths, and reference
  allowlists.

## What The Server Deliberately Does Not Do

The server does not let a model:

- choose arbitrary upstream base URLs;
- provide credentials as tool arguments;
- bypass the confirmation gate for process execution unless the operator
  explicitly enables the low-level direct execution tool;
- perform geospatial analysis inside the MCP server or model context instead of
  through OGC API - Processes;
- load large feature coordinates into model context by default.

## Main Workflows

### Discover Data

```text
ogc_servers_list
  -> ogc_features_list_collections
  -> ogc_features_describe_collection
  -> ogc_features_get_items
```

### Search Metadata

```text
ogc_servers_list
  -> ogc_records_list_collections
  -> ogc_records_search
  -> ogc_records_get_record
```

### Execute A Process Safely

```text
ogc_servers_list
  -> ogc_processes_list
  -> ogc_processes_describe
  -> ogc_proxy_create_plan
  -> ogc_proxy_update_plan, if inputs need correction
  -> show confirmation_prompt.execute_request to the user
  -> ogc_proxy_confirm_plan
  -> ogc_proxy_execute_plan
```

## Design Values

- Discovery before execution.
- Operator-owned registry, not model-owned URLs.
- Human confirmation before state-changing analysis.
- Exact upstream process identifiers, not invented aliases.
- Compact model-facing summaries, not unbounded raw payloads.
- Credentials and deployment secrets stay outside model context.
- Deterministic tests for behavior that matters.
