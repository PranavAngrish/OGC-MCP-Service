import assert from "node:assert/strict";
import test from "node:test";
import { publicGatewayError } from "./errors.mjs";

test("turns provider rate limits into actionable public errors", () => {
  const error = new Error("429 status code (no body)");
  const result = publicGatewayError(error);
  assert.equal(result.code, "provider_rate_limit");
  assert.equal(result.retryable, true);
  assert.match(result.message, /Gemini.*HTTP 429/);
  assert.doesNotMatch(result.message, /no body/);
});

test("recognizes structured provider status values", () => {
  const result = publicGatewayError({ status: 503 });
  assert.equal(result.code, "provider_unavailable");
  assert.equal(result.retryable, true);
});
