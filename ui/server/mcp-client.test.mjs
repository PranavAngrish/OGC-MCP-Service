import assert from "node:assert/strict";
import test from "node:test";
import {
  mcpToolRequestOptions,
  resolveMcpToolTimeoutMs,
} from "./mcp-client.mjs";

test("uses a three-minute MCP tool timeout by default", () => {
  assert.equal(resolveMcpToolTimeoutMs(), 180_000);
  assert.equal(resolveMcpToolTimeoutMs(""), 180_000);
  assert.equal(resolveMcpToolTimeoutMs("not-a-number"), 180_000);
});

test("bounds configured MCP tool timeouts", () => {
  assert.equal(resolveMcpToolTimeoutMs("1000"), 10_000);
  assert.equal(resolveMcpToolTimeoutMs("240000"), 240_000);
  assert.equal(resolveMcpToolTimeoutMs("3600000"), 900_000);
});

test("adds the configured timeout while preserving cancellation", () => {
  const controller = new AbortController();
  const options = mcpToolRequestOptions(
    { signal: controller.signal },
    "240000",
  );

  assert.equal(options.timeout, 240_000);
  assert.equal(options.signal, controller.signal);
});

test("preserves a call-specific timeout override", () => {
  const options = mcpToolRequestOptions({ timeout: 45_000 }, "240000");
  assert.equal(options.timeout, 45_000);
});
