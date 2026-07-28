function errorStatus(error) {
  const value = Number(error?.status);
  if (Number.isInteger(value)) return value;
  const message = error instanceof Error ? error.message : String(error || "");
  const match = message.match(/\b(4\d\d|5\d\d)\b/);
  return match ? Number(match[1]) : undefined;
}

export function publicGatewayError(error) {
  const status = errorStatus(error);
  if (status === 429) {
    return {
      code: "provider_rate_limit",
      retryable: true,
      message: "Gemini is rate-limiting this project (HTTP 429). Wait about a minute and try again. If it persists, check this API key's Gemini quota or billing configuration.",
    };
  }
  if (status === 401 || status === 403) {
    return {
      code: "provider_authentication",
      retryable: false,
      message: "Gemini rejected the configured API key. Check GEMINI_API_KEY and that the project can use the selected model.",
    };
  }
  if (status && status >= 500) {
    return {
      code: "provider_unavailable",
      retryable: true,
      message: `The model provider is temporarily unavailable (HTTP ${status}). Please try again shortly.`,
    };
  }
  return {
    code: "gateway_error",
    retryable: false,
    message: error instanceof Error ? error.message : "An unexpected gateway error occurred.",
  };
}
