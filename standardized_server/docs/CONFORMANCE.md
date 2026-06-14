# Experimental Conformance Checklist

This checklist describes the behavior expected from implementations of the
experimental OGC API MCP tool contract in `spec/ogc-mcp-tool-contract.json`.
It is not an OGC conformance class.

## Registry

- [ ] The implementation exposes stable server IDs.
- [ ] MCP callers cannot send arbitrary upstream base URLs.
- [ ] Server metadata responses omit credentials and secret values.
- [ ] Module defaults are explicit and operator-configured.

## Security

- [ ] Upstream requests are limited to registered deployments.
- [ ] Generic paths are relative and reject absolute URLs.
- [ ] Credentials are injected outside model-visible arguments.
- [ ] Process execution references are validated recursively.
- [ ] Private network access is disabled by default.
- [ ] Redirects are not followed without validation.
- [ ] Response sizes and request durations are bounded.
- [ ] Infrastructure-level egress restrictions are recommended for production.

## Results

- [ ] Every success contains `ok`, `operation`, `server`, `request`, `response`,
      and `data`.
- [ ] Every expected failure contains `ok=false`, `operation`, and `error`.
- [ ] Error responses use stable machine-readable codes.
- [ ] Upstream payloads are preserved unless a documented transformation exists.

## OGC API - Common

- [ ] Landing page retrieval is supported.
- [ ] Conformance declaration retrieval is supported.
- [ ] Safe read-only relative resource access is supported.

## OGC API - Features

- [ ] Collection listing is supported.
- [ ] Collection metadata retrieval is supported.
- [ ] Feature item listing is supported.
- [ ] Single feature retrieval is supported.

## OGC API - Records

- [ ] Catalogue collection listing is supported.
- [ ] Record search is supported.
- [ ] Single record retrieval is supported.

## OGC API - Processes

- [ ] Process listing is supported.
- [ ] Process description retrieval is supported.
- [ ] Execute requests preserve advertised input/output names.
- [ ] Inline and referenced process inputs are supported.
- [ ] `Prefer: respond-async` can be requested.
- [ ] Job listing, status, results, and dismissal are supported.

