import OpenAI from "openai";
import {
  approvalRequestCount,
  clearApprovalSession,
  registerApprovalRequest,
} from "./approvals.mjs";
import {
  backgroundJobCount,
  clearBackgroundJobs,
  extractBackgroundJob,
  stopTrackedJob,
  trackBackgroundJob,
} from "./background-jobs.mjs";
import {
  activityResultPreview,
  activityWarnings,
  compactToolResult,
  eventTiming,
  safeToolArguments,
  summarizeToolOutcome,
  summarizeToolPurpose,
} from "./activity-events.mjs";
import { callMcpTool, listMcpTools } from "./mcp-client.mjs";
import {
  blockedEvidenceAnswer,
  evidenceQualificationNote,
  featureEvidence,
} from "./evidence.mjs";
import { findMemoryHandle, structuredToolPayload } from "./map-artifacts.mjs";
import { AGENT_INSTRUCTIONS, MAX_TOOL_ROUNDS, toolLabel } from "./prompts.mjs";
import {
  clearResultArtifactSession,
  prepareResultArtifacts,
} from "./result-artifacts.mjs";
import { modelToolResultText } from "./model-output.mjs";
import { isModelCallableTool, modelVisibleMcpTools } from "./tool-policy.mjs";
import {
  createWorkflowEventEmitter,
  workflowManifestPayload,
} from "./workflow-events.mjs";

const sessions = new Map();
const GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/";

const model = process.env.GEMINI_MODEL || "gemini-3.1-flash-lite";
const reasoningEffort = process.env.GEMINI_REASONING_EFFORT || "medium";

function geminiClient() {
  const apiKey = process.env.GEMINI_API_KEY || process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not configured in the gateway environment.");
  }
  return new OpenAI({ apiKey, baseURL: GEMINI_BASE_URL });
}

function asFunctionTool(tool) {
  return {
    type: "function",
    function: {
      name: tool.name,
      description: tool.description || `Call the ${tool.name} MCP tool.`,
      parameters: tool.inputSchema || { type: "object", properties: {} },
    },
  };
}

function parseArguments(value) {
  if (!value) return {};
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function messageText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

function resultText(result) {
  if (result?.structuredContent) return JSON.stringify(result.structuredContent);
  if (!Array.isArray(result?.content)) return JSON.stringify(result ?? null);
  return result.content
    .map((item) => {
      if (item.type === "text") return item.text;
      if (item.type === "resource_link") return JSON.stringify(item);
      return `[${item.type} content]`;
    })
    .join("\n");
}

export function clearSession(sessionId) {
  sessions.delete(sessionId);
  clearBackgroundJobs(sessionId);
  clearResultArtifactSession(sessionId);
  clearApprovalSession(sessionId);
}

async function executeAgentTurn({
  message,
  sessionId,
  responseId,
  emit,
  emitWorkflowEvent,
  signal,
}) {
  const client = geminiClient();
  const callTool = (name, args, options = {}) => callMcpTool(name, args, {
    ...options,
    signal,
  });
  const mcpTools = modelVisibleMcpTools(await listMcpTools());
  const tools = mcpTools.map(asFunctionTool);
  const priorMessages = sessions.get(sessionId)?.messages || [
    { role: "system", content: AGENT_INSTRUCTIONS },
  ];
  const messages = [...priorMessages, { role: "user", content: message }];
  const mappedMemoryHandles = new Set();
  let latestFeatureEvidence = null;
  const featureQualifications = new Set();
  const turnStartedAt = Date.now();
  const emitEvent = (event, data, now = Date.now()) => {
    emit(event, { ...data, ...eventTiming(turnStartedAt, now) });
  };
  emitEvent("meta", { sessionId, model, provider: "gemini", toolCount: tools.length });
  emitEvent("status", {
    id: "understand",
    title: "Understanding your request",
    detail: "Identifying the requested outcome, unresolved decisions, and relevant OGC capabilities.",
    status: "running",
  });
  for (let round = 0; round < MAX_TOOL_ROUNDS; round += 1) {
    if (round > 0) {
      emitEvent("status", {
        id: `synthesize-${round - 1}`,
        title: "Tool results reviewed",
        detail: "The previous tool results have been incorporated into the next step.",
        status: "complete",
      });
    }
    if (signal?.aborted) throw new Error("The request was cancelled.");
    emitEvent("reasoning_delta", {
      id: `plan-${round}`,
      summaryType: "action",
      delta:
        round === 0
          ? "I’m identifying the OGC capabilities needed for this request."
          : "I’m reviewing the tool results and deciding whether another MCP step is needed.",
    });

    const completion = await client.chat.completions.create(
      {
        model,
        messages,
        tools,
        tool_choice: "auto",
        reasoning_effort: reasoningEffort,
      },
      { signal },
    );
    const assistantMessage = completion.choices[0]?.message;
    if (!assistantMessage) throw new Error("Gemini completed without returning a message.");

    messages.push(assistantMessage);
    emitEvent("status", {
      id: "understand",
      title: "Request understood",
      detail: "A safe next action has been selected from the connected services.",
      status: "complete",
    });
    if (round === 0) {
      emitWorkflowEvent("intent_recognized", {
        activityId: "understand",
        payload: {
          title: "Request understood",
          detail: "A safe next action was selected from the connected OGC services.",
          status: "complete",
        },
      });
    }

    const calls = assistantMessage.tool_calls || [];
    if (calls.length === 0) {
      const proposedAnswer = messageText(assistantMessage.content);
      const blockedAnswer = blockedEvidenceAnswer(latestFeatureEvidence);
      const qualificationNote = evidenceQualificationNote({
        safeToAnswer: latestFeatureEvidence?.safeToAnswer === true,
        qualifications: [...featureQualifications],
      });
      const answer = blockedAnswer || (
        qualificationNote && proposedAnswer
          ? `${proposedAnswer}\n\n${qualificationNote}`
          : proposedAnswer
      );
      if (!answer) throw new Error("Gemini completed without returning an answer.");
      sessions.set(sessionId, { messages });
      emitEvent("answer", { content: answer });
      emitWorkflowEvent("workflow_completed", {
        activityId: `workflow-${responseId}`,
        payload: {
          title: "Workflow completed",
          detail: "The response was completed successfully.",
          status: "complete",
        },
      });
      emitEvent("done", { responseId: completion.id });
      return;
    }

    const commentary = messageText(assistantMessage.content);
    if (commentary) {
      emitEvent("reasoning_delta", {
        id: `commentary-${round}`,
        summaryType: "assistant_commentary",
        delta: commentary,
      });
    }

    for (const call of calls) {
      if (signal?.aborted) throw new Error("The request was cancelled.");
      if (call.type !== "function") continue;
      const args = parseArguments(call.function.arguments);
      const activityId = call.id;
      const toolStartedAtMs = Date.now();
      const toolStartedAt = new Date(toolStartedAtMs).toISOString();
      emitEvent("tool_start", {
        id: activityId,
        name: call.function.name,
        title: toolLabel(call.function.name),
        purpose: summarizeToolPurpose(call.function.name, args),
        arguments: safeToolArguments(args),
        status: "running",
        round: round + 1,
        startedAt: toolStartedAt,
      }, toolStartedAtMs);
      emitWorkflowEvent("step_started", {
        activityId,
        atMs: toolStartedAtMs,
        payload: {
          title: toolLabel(call.function.name),
          detail: summarizeToolPurpose(call.function.name, args),
          status: "running",
          toolName: call.function.name,
          round: round + 1,
        },
      });

      let output;
      if (!isModelCallableTool(call.function.name)) {
        output = JSON.stringify({
          ok: false,
          error: "This internal renderer tool is not callable by the conversational model.",
        });
        const rejectedAtMs = Date.now();
        emitEvent("tool_result", {
          id: activityId,
          name: call.function.name,
          title: toolLabel(call.function.name),
          summary: "Rejected an internal-only renderer tool call.",
          result: { ok: false, error: "Internal renderer tool calls are gateway-only." },
          preview: output,
          warnings: [],
          isError: true,
          status: "error",
          startedAt: toolStartedAt,
          completedAt: new Date(rejectedAtMs).toISOString(),
          durationMs: Math.max(0, rejectedAtMs - toolStartedAtMs),
        }, rejectedAtMs);
        emitWorkflowEvent("step_completed", {
          activityId,
          atMs: rejectedAtMs,
          payload: {
            title: toolLabel(call.function.name),
            detail: "Rejected an internal-only renderer tool call.",
            status: "error",
            toolName: call.function.name,
          },
        });
        messages.push({
          role: "tool",
          tool_call_id: call.id,
          name: call.function.name,
          content: output,
        });
        continue;
      }
      try {
        const result = await callTool(call.function.name, args);
        if (signal?.aborted) throw new Error("The request was cancelled.");
        output = resultText(result);
        const resultPayload = structuredToolPayload(result);
        const currentFeatureEvidence = featureEvidence(call.function.name, resultPayload);
        if (currentFeatureEvidence) {
          latestFeatureEvidence = currentFeatureEvidence;
          for (const qualification of currentFeatureEvidence.qualifications || []) {
            featureQualifications.add(qualification);
          }
        }
        const approvalRequest = registerApprovalRequest({
          sessionId,
          targetMessageId: responseId,
          payload: resultPayload,
        });
        if (approvalRequest) {
          emitEvent("approval_request", {
            targetMessageId: responseId,
            request: approvalRequest,
          });
          emitWorkflowEvent("approval_required", {
            activityId: `approval-${approvalRequest.challengeId}`,
            payload: {
              title: "Approval required",
              detail: "The validated execution plan requires explicit user approval.",
              status: "waiting",
              request: approvalRequest,
            },
          });
        }
        let artifacts = null;
        let artifactPreparationFailed = false;
        try {
          artifacts = await prepareResultArtifacts({
            toolName: call.function.name,
            args,
            activityId,
            result,
            callTool,
            sessionId,
          });
        } catch {
          artifactPreparationFailed = true;
          emitEvent("artifact_status", {
            activityId,
            manifestId: `manifest-${activityId}`,
            outputId: "result",
            stage: "orchestration",
            status: "error",
            detail: "The tool completed, but the gateway could not prepare its output manifest.",
          });
          emitWorkflowEvent("presentation_status", {
            activityId,
            payload: {
              manifestId: `manifest-${activityId}`,
              outputId: "result",
              stage: "orchestration",
              status: "error",
              detail: "The tool completed, but the gateway could not prepare its output manifest.",
            },
          });
        }
        output = modelToolResultText({
          toolName: call.function.name,
          payload: resultPayload,
          rawOutput: output,
          artifacts,
          preparationFailed: artifactPreparationFailed,
          isError: Boolean(result?.isError),
        });
        const toolCompletedAtMs = Date.now();
        emitEvent("tool_result", {
          id: activityId,
          name: call.function.name,
          title: toolLabel(call.function.name),
          summary: summarizeToolOutcome(
            call.function.name,
            resultPayload,
            Boolean(result?.isError),
            artifacts?.manifest,
          ),
          result: compactToolResult(resultPayload, artifacts?.manifest),
          preview: activityResultPreview(resultPayload, output),
          warnings: activityWarnings(resultPayload, artifacts?.manifest),
          isError: Boolean(result?.isError),
          status: result?.isError ? "error" : "complete",
          startedAt: toolStartedAt,
          completedAt: new Date(toolCompletedAtMs).toISOString(),
          durationMs: Math.max(0, toolCompletedAtMs - toolStartedAtMs),
        }, toolCompletedAtMs);
        emitWorkflowEvent("step_completed", {
          activityId,
          atMs: toolCompletedAtMs,
          payload: {
            title: toolLabel(call.function.name),
            detail: summarizeToolOutcome(
              call.function.name,
              resultPayload,
              Boolean(result?.isError),
              artifacts?.manifest,
            ),
            status: result?.isError ? "error" : "complete",
            toolName: call.function.name,
          },
        });

        const backgroundJob = extractBackgroundJob(call.function.name, result);
        if (backgroundJob) {
          trackBackgroundJob({
            sessionId,
            targetMessageId: responseId,
            job: backgroundJob,
          });
        }

        const retrievedHandle = call.function.name === "ogc_proxy_memory_retrieve"
          ? String(resultPayload?.handle || args.handle || "")
          : "";
        const memoryHandle = findMemoryHandle(resultPayload)
          || (/^mem_[a-f0-9]{32}$/.test(retrievedHandle) ? retrievedHandle : "");
        if (signal?.aborted) throw new Error("The request was cancelled.");
        if (artifacts?.manifest) {
          emitEvent("output_manifest", { activityId, manifest: artifacts.manifest });
          emitWorkflowEvent("output_manifest_upserted", {
            activityId: `artifact-${artifacts.manifest.manifestId}-manifest`,
            payload: workflowManifestPayload(artifacts.manifest),
          });
          for (const outputArtifact of artifacts.manifest.outputs || []) {
            if (!outputArtifact.clarificationRequest) continue;
            emitWorkflowEvent("clarification_required", {
              activityId: `clarification-${artifacts.manifest.manifestId}-${outputArtifact.id}`,
              payload: {
                title: `Clarification required: ${outputArtifact.title}`,
                detail: outputArtifact.clarificationRequest.issues?.[0]?.question
                  || "More information is required before this output can be presented safely.",
                status: "waiting",
                manifestId: artifacts.manifest.manifestId,
                outputId: outputArtifact.id,
                request: outputArtifact.clarificationRequest,
              },
            });
          }
          for (const event of artifacts.artifactEvents || []) {
            emitEvent("artifact_status", { activityId, ...event });
            emitWorkflowEvent("presentation_status", {
              activityId,
              payload: event,
            });
          }
        }
        if (artifacts?.visualization && (!memoryHandle || !mappedMemoryHandles.has(memoryHandle))) {
          emitEvent("map_data", { activityId, visualization: artifacts.visualization });
          if (memoryHandle) mappedMemoryHandles.add(memoryHandle);
        }
        if (
          call.function.name === "ogc_jobs_get_results"
          && !result?.isError
          && resultPayload
          && resultPayload?.ok !== false
          && artifacts?.manifest?.overallState !== "pending"
        ) {
          stopTrackedJob(sessionId, args.job_id, resultPayload.server?.id || args.server_id);
        }
      } catch (error) {
        output = JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
        const errorPayload = JSON.parse(output);
        const toolCompletedAtMs = Date.now();
        emitEvent("tool_result", {
          id: activityId,
          name: call.function.name,
          title: toolLabel(call.function.name),
          summary: summarizeToolOutcome(call.function.name, errorPayload, true),
          result: compactToolResult(errorPayload),
          preview: activityResultPreview(errorPayload, output),
          warnings: [],
          isError: true,
          status: "error",
          startedAt: toolStartedAt,
          completedAt: new Date(toolCompletedAtMs).toISOString(),
          durationMs: Math.max(0, toolCompletedAtMs - toolStartedAtMs),
        }, toolCompletedAtMs);
        emitWorkflowEvent("step_completed", {
          activityId,
          atMs: toolCompletedAtMs,
          payload: {
            title: toolLabel(call.function.name),
            detail: summarizeToolOutcome(call.function.name, errorPayload, true),
            status: "error",
            toolName: call.function.name,
          },
        });
      }

      messages.push({
        role: "tool",
        tool_call_id: call.id,
        name: call.function.name,
        content: output,
      });
    }

    emitEvent("status", {
      id: `synthesize-${round}`,
      title: "Reviewing returned information",
      detail: "Checking the result, unresolved inputs, and the next safe action.",
      status: "running",
    });
  }

  emitEvent("status", {
    id: `synthesize-${MAX_TOOL_ROUNDS - 1}`,
    title: "Tool-call limit reached",
    detail: "The request could not be completed within the allowed number of tool rounds.",
    status: "error",
  });
  throw new Error(`The agent exceeded the ${MAX_TOOL_ROUNDS}-round tool-call limit.`);
}

export async function runAgentTurn({ message, sessionId, responseId, emit, signal }) {
  const emitWorkflowEvent = createWorkflowEventEmitter({
    emit,
    sessionId,
    turnId: responseId,
    targetMessageId: responseId,
    runId: `agent-${responseId}`,
  });
  try {
    return await executeAgentTurn({
      message,
      sessionId,
      responseId,
      emit,
      emitWorkflowEvent,
      signal,
    });
  } catch (error) {
    emitWorkflowEvent("workflow_failed", {
      activityId: `workflow-${responseId}`,
      payload: {
        title: "Workflow failed",
        detail: "The workflow could not be completed.",
        status: "error",
      },
    });
    throw error;
  }
}

export const agentStatus = () => ({
  model,
  provider: "gemini",
  providerConfigured: Boolean(process.env.GEMINI_API_KEY || process.env.OPENAI_API_KEY),
  sessions: sessions.size,
  backgroundJobs: backgroundJobCount(),
  pendingApprovals: approvalRequestCount(),
});
