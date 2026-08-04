import express from "express";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { agentStatus, clearSession, runAgentTurn } from "./agent.mjs";
import { decideApproval } from "./approvals.mjs";
import { subscribeSessionEvents } from "./background-jobs.mjs";
import { publicGatewayError } from "./errors.mjs";
import { callMcpTool, listMcpTools } from "./mcp-client.mjs";
import { retrieveSessionArtifact } from "./result-artifacts.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const uiDirectory = path.resolve(directory, "..");
const distDirectory = path.join(uiDirectory, "dist");
const port = Number(process.env.UI_GATEWAY_PORT || 8787);

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "64kb" }));

app.get("/api/health", async (_request, response) => {
  const base = agentStatus();
  try {
    const tools = await listMcpTools();
    response.json({ ok: true, ...base, mcpConnected: true, toolCount: tools.length });
  } catch (error) {
    response.status(503).json({
      ok: false,
      ...base,
      mcpConnected: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

app.delete("/api/sessions/:sessionId", (request, response) => {
  clearSession(request.params.sessionId);
  response.status(204).end();
});

app.get("/api/sessions/:sessionId/events", (request, response) => {
  const sessionId = request.params.sessionId;
  if (!sessionId || sessionId.length > 200) {
    response.status(400).json({ error: "invalid session id" });
    return;
  }
  response.status(200);
  response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  response.setHeader("Cache-Control", "no-cache, no-transform");
  response.setHeader("Connection", "keep-alive");
  response.flushHeaders();

  const emit = (event, data) => {
    if (!response.writableEnded) response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };
  const unsubscribe = subscribeSessionEvents(sessionId, emit);
  emit("ready", { sessionId });
  const heartbeat = setInterval(() => {
    if (!response.writableEnded) response.write(": keep-alive\n\n");
  }, 15_000);
  response.on("close", () => {
    clearInterval(heartbeat);
    unsubscribe();
  });
});

app.post("/api/sessions/:sessionId/approvals/:challengeId", async (request, response) => {
  const sessionId = request.params.sessionId;
  const challengeId = request.params.challengeId;
  if (
    !sessionId
    || sessionId.length > 200
    || !/^[0-9a-f-]{36}$/i.test(challengeId)
    || typeof request.body?.approved !== "boolean"
  ) {
    response.status(400).json({
      error: "A valid session challenge and an explicit boolean decision are required.",
    });
    return;
  }
  const result = await decideApproval({
    sessionId,
    challengeId,
    approved: request.body.approved,
    callTool: callMcpTool,
  });
  response.status(result.status).json(
    result.ok
      ? result
      : { ok: false, error: result.error },
  );
});

app.get("/api/artifacts/:handle", async (request, response) => {
  const sessionId = typeof request.query.sessionId === "string" ? request.query.sessionId : "";
  const handle = request.params.handle;
  if (!sessionId || sessionId.length > 200 || !/^art_[a-f0-9]{32}$/.test(handle)) {
    response.status(400).json({ error: "A valid session-scoped artifact handle is required." });
    return;
  }
  const artifact = await retrieveSessionArtifact({
    sessionId,
    handle,
    callTool: callMcpTool,
  });
  if (!artifact.ok) {
    response.status(artifact.status).json({ error: artifact.error });
    return;
  }
  response.status(200);
  response.setHeader("Content-Type", artifact.mediaType);
  const safeInlineImage = /^image\/(?:png|jpeg|webp|gif|avif)(?:;|$)/i.test(artifact.mediaType);
  response.setHeader(
    "Content-Disposition",
    `${safeInlineImage ? "inline" : "attachment"}; filename="${artifact.filename}"`,
  );
  response.setHeader("Cache-Control", "private, no-store");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.send(artifact.data);
});

app.post("/api/chat", async (request, response) => {
  const message = typeof request.body?.message === "string" ? request.body.message.trim() : "";
  const sessionId =
    typeof request.body?.sessionId === "string" && request.body.sessionId
      ? request.body.sessionId
      : randomUUID();
  const responseId =
    typeof request.body?.responseId === "string" && request.body.responseId.length <= 200
      ? request.body.responseId
      : randomUUID();

  if (!message || message.length > 20_000) {
    response.status(400).json({ error: "message must contain between 1 and 20,000 characters" });
    return;
  }

  response.status(200);
  response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  response.setHeader("Cache-Control", "no-cache, no-transform");
  response.setHeader("Connection", "keep-alive");
  response.flushHeaders();

  const controller = new AbortController();
  response.on("close", () => {
    if (!response.writableEnded) controller.abort();
  });

  const emit = (event, data) => {
    if (!response.writableEnded) {
      response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    }
  };

  try {
    await runAgentTurn({ message, sessionId, responseId, emit, signal: controller.signal });
  } catch (error) {
    emit("error", publicGatewayError(error));
  } finally {
    response.end();
  }
});

app.use("/api", (_request, response) => {
  response.status(404).json({ error: "API route not found" });
});

app.use(express.static(distDirectory));
app.use((_request, response) => response.sendFile(path.join(distDirectory, "index.html")));

app.listen(port, "127.0.0.1", (error) => {
  if (error) {
    console.error(`Unable to start the Terra Console gateway: ${error.message}`);
    process.exitCode = 1;
    return;
  }
  console.log(`Terra Console gateway listening on http://127.0.0.1:${port}`);
});
