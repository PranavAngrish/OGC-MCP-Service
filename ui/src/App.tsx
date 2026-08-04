import { AnimatePresence } from "motion/react";
import {
  Bot,
  ChevronLeft,
  CircleHelp,
  Compass,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import EmptyState from "./components/EmptyState";
import MessageBubble from "./components/MessageBubble";
import { updateActivities } from "./lib/activities";
import { decidePlanApproval, streamChat, subscribeSessionEvents } from "./lib/chat";
import { normalizeOutputManifest, upsertOutputManifest } from "./lib/outputs";
import type {
  GatewayHealth,
  MapVisualization,
  Message,
  ApprovalRequest,
  OutputManifestV1,
  StreamEvent,
} from "./types";

const makeId = () => crypto.randomUUID();

function mapFromEvent(event: StreamEvent): MapVisualization | null {
  const candidate = event.data.visualization;
  if (!candidate || typeof candidate !== "object") return null;
  const map = candidate as Partial<MapVisualization>;
  if (typeof map.id !== "string" || typeof map.title !== "string" || !Array.isArray(map.layers)) {
    return null;
  }
  return map as MapVisualization;
}

function withVisualization(message: Message, visualization: MapVisualization): Message {
  const maps = message.maps || [];
  const exists = maps.some((map) => map.id === visualization.id);
  return {
    ...message,
    maps: exists
      ? maps.map((map) => (map.id === visualization.id ? visualization : map))
      : [...maps, visualization].slice(-4),
  };
}

function manifestFromEvent(event: StreamEvent): OutputManifestV1 | null {
  const workflow = event.data.event && typeof event.data.event === "object"
    ? event.data.event as Record<string, unknown>
    : event.data;
  const payload = workflow.payload && typeof workflow.payload === "object"
    ? workflow.payload as Record<string, unknown>
    : {};
  return normalizeOutputManifest(event.data.manifest || payload.manifest);
}

function withOutputManifest(message: Message, manifest: OutputManifestV1): Message {
  return {
    ...message,
    outputManifests: upsertOutputManifest(message.outputManifests || [], manifest),
  };
}

function approvalFromEvent(event: StreamEvent): ApprovalRequest | null {
  const candidate = event.data.request;
  if (!candidate || typeof candidate !== "object") return null;
  const request = candidate as Record<string, unknown>;
  if (
    typeof request.challengeId !== "string"
    || typeof request.planId !== "string"
    || typeof request.digest !== "string"
    || typeof request.expiresAt !== "string"
  ) return null;
  return {
    challengeId: request.challengeId,
    planId: request.planId,
    serverId: typeof request.serverId === "string" ? request.serverId : "",
    executeRequest: request.executeRequest,
    inputContext: request.inputContext,
    steps: Array.isArray(request.steps) ? request.steps : [],
    digest: request.digest,
    expiresAt: request.expiresAt,
    status: "pending",
  };
}

function withApprovalRequest(message: Message, request: ApprovalRequest): Message {
  const current = message.approvalRequests || [];
  const index = current.findIndex((item) => item.challengeId === request.challengeId);
  return {
    ...message,
    approvalRequests: index < 0
      ? [...current, request].slice(-4)
      : current.map((item, itemIndex) => itemIndex === index ? request : item),
  };
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sessionId, setSessionId] = useState(makeId);
  const [controller, setController] = useState<AbortController | null>(null);
  const scrollAnchor = useRef<HTMLDivElement>(null);
  const chatScroll = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const busy = Boolean(controller);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => response.json())
      .then(setHealth)
      .catch((error: Error) => setHealth({ ok: false, error: error.message }));
  }, []);

  useEffect(() => subscribeSessionEvents(sessionId, (event) => {
    const targetMessageId = String(event.data.targetMessageId || "");
    if (!targetMessageId) return;
    setMessages((current) => current.map((message) => {
      if (message.id !== targetMessageId) return message;
      if (event.event === "map_data") {
        const visualization = mapFromEvent(event);
        return visualization ? withVisualization(message, visualization) : message;
      }
      if (event.event === "output_manifest") {
        const manifest = manifestFromEvent(event);
        if (!manifest) return message;
        return {
          ...withOutputManifest(message, manifest),
          activities: updateActivities(message.activities || [], event),
        };
      }
      if (["job_status", "artifact_status", "workflow_event"].includes(event.event)) {
        const manifest = event.event === "workflow_event" ? manifestFromEvent(event) : null;
        const updatedMessage = manifest ? withOutputManifest(message, manifest) : message;
        return {
          ...updatedMessage,
          activities: updateActivities(updatedMessage.activities || [], event),
        };
      }
      return message;
    }));
  }), [sessionId]);

  useEffect(() => {
    if (stickToBottom.current) {
      scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  const connectionLabel = useMemo(() => {
    if (!health) return "Connecting";
    if (health.mcpConnected && health.providerConfigured) return "Systems ready";
    if (!health.providerConfigured) return "API key needed";
    return "MCP unavailable";
  }, [health]);

  const startNewChat = async () => {
    controller?.abort();
    await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }).catch(() => undefined);
    setSessionId(makeId());
    setMessages([]);
    setController(null);
    setInput("");
  };

  const submit = async (value = input) => {
    const content = value.trim();
    if (!content || busy) return;

    const userMessage: Message = {
      id: makeId(), role: "user", content, createdAt: new Date(),
    };
    const assistantId = makeId();
    const assistantMessage: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      createdAt: new Date(),
      pending: true,
      activities: [],
      maps: [],
      outputManifests: [],
      approvalRequests: [],
    };
    const abortController = new AbortController();
    stickToBottom.current = true;
    setController(abortController);
    setInput("");
    setMessages((current) => [...current, userMessage, assistantMessage]);

    const handleEvent = (event: StreamEvent) => {
      setMessages((current) =>
        current.map((message) => {
          if (message.id !== assistantId) return message;
          if ([
            "status",
            "reasoning_delta",
            "tool_start",
            "tool_result",
            "artifact_status",
            "workflow_event",
          ].includes(event.event)) {
            const manifest = event.event === "workflow_event" ? manifestFromEvent(event) : null;
            const updatedMessage = manifest ? withOutputManifest(message, manifest) : message;
            return {
              ...updatedMessage,
              activities: updateActivities(updatedMessage.activities || [], event),
            };
          }
          if (event.event === "answer") {
            return { ...message, content: String(event.data.content || "") };
          }
          if (event.event === "approval_request") {
            const request = approvalFromEvent(event);
            return request ? withApprovalRequest(message, request) : message;
          }
          if (event.event === "map_data") {
            const visualization = mapFromEvent(event);
            return visualization ? withVisualization(message, visualization) : message;
          }
          if (event.event === "output_manifest") {
            const manifest = manifestFromEvent(event);
            if (!manifest) return message;
            return {
              ...withOutputManifest(message, manifest),
              activities: updateActivities(message.activities || [], event),
            };
          }
          if (event.event === "done") {
            const cancelled = event.data.cancelled === true;
            return {
              ...message,
              pending: false,
              activities: (message.activities || []).map((activity) =>
                activity.status === "running"
                  && activity.kind !== "artifact"
                  && !activity.id.startsWith("background-job-")
                  ? { ...activity, status: cancelled ? "cancelled" : "complete" }
                  : activity,
              ),
            };
          }
          if (event.event === "error") {
            return {
              ...message,
              pending: false,
              error: String(event.data.message),
              activities: (message.activities || []).map((activity) =>
                activity.status === "running" ? { ...activity, status: "error" } : activity,
              ),
            };
          }
          return message;
        }),
      );
    };

    try {
      await streamChat(content, sessionId, assistantId, handleEvent, abortController.signal);
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        handleEvent({ event: "done", data: { cancelled: true } });
      } else {
        handleEvent({ event: "error", data: { message: (error as Error).message } });
      }
    } finally {
      setController(null);
      textarea.current?.focus();
    }
  };

  const decideApproval = async (
    messageId: string,
    challengeId: string,
    approved: boolean,
  ) => {
    if (busy) return;
    setMessages((current) => current.map((message) => (
      message.id !== messageId
        ? message
        : {
          ...message,
          approvalRequests: (message.approvalRequests || []).map((request) =>
            request.challengeId === challengeId
              ? { ...request, status: "submitting", error: undefined }
              : request
          ),
        }
    )));
    try {
      const decision = await decidePlanApproval(sessionId, challengeId, approved);
      setMessages((current) => current.map((message) => (
        message.id !== messageId
          ? message
          : {
            ...message,
            approvalRequests: (message.approvalRequests || []).map((request) =>
              request.challengeId === challengeId
                ? { ...request, status: decision.decision }
                : request
            ),
          }
      )));
      await submit(
        decision.decision === "approved"
          ? `I approved the exact displayed request for plan ${decision.planId}. Continue with that plan.`
          : `I rejected the exact displayed request for plan ${decision.planId}. Do not execute it.`,
      );
    } catch (error) {
      setMessages((current) => current.map((message) => (
        message.id !== messageId
          ? message
          : {
            ...message,
            approvalRequests: (message.approvalRequests || []).map((request) =>
              request.challengeId === challengeId
                ? { ...request, status: "error", error: (error as Error).message }
                : request
            ),
          }
      )));
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit();
  };

  return (
    <div className={`app-shell ${sidebarOpen ? "sidebar-visible" : "sidebar-hidden"}`}>
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><Compass size={20} /></div>
          <div><strong>Terra</strong><span>OGC Console</span></div>
          <button className="icon-button desktop-only" onClick={() => setSidebarOpen(false)}>
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button className="new-chat" onClick={startNewChat}>
          <MessageSquarePlus size={17} /> New conversation <span>⌘ K</span>
        </button>

        <nav className="sidebar-nav">
          <span className="sidebar-label">Workspace</span>
          <button className="nav-active"><Sparkles size={16} /> Agent chat</button>
          <button><Bot size={16} /> Tool explorer <small>{health?.toolCount ?? "—"}</small></button>
        </nav>

        <div className="sidebar-spacer" />

        <div className="system-card">
          <div className="system-card-header">
            <span className={health?.mcpConnected ? "status-dot online" : "status-dot"} />
            <strong>{connectionLabel}</strong>
          </div>
          <p>{health?.model || "Model gateway"}</p>
          <div className="system-metric"><span>MCP tools</span><b>{health?.toolCount ?? "—"}</b></div>
          <div className="system-metric"><span>Data boundary</span><b>Protected</b></div>
        </div>

        <div className="sidebar-footer">
          <ShieldCheck size={16} /> Human-confirmed execution
          <CircleHelp size={16} />
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button" onClick={() => setSidebarOpen((value) => !value)}>
            {sidebarOpen ? <ChevronLeft size={19} /> : <Menu size={19} />}
          </button>
          <div className="conversation-title">
            <span>Conversation</span>
            <strong>{messages.length ? "Geospatial workspace" : "New exploration"}</strong>
          </div>
          <div className="topbar-actions">
            <span className="model-chip"><i /> {health?.model || "LLM"}</span>
            <span className="secure-chip"><ShieldCheck size={14} /> MCP secured</span>
          </div>
        </header>

        <div className="chat-stage">
          <div
            className="chat-scroll"
            ref={chatScroll}
            onScroll={() => {
              const element = chatScroll.current;
              if (!element) return;
              stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 160;
            }}
          >
            {messages.length === 0 ? (
              <EmptyState onSelect={(prompt) => void submit(prompt)} />
            ) : (
              <div className="messages">
                <AnimatePresence initial={false}>
                  {messages.map((message) => (
                    <MessageBubble
                      message={message}
                      onApprovalDecision={(messageId, challengeId, approved) =>
                        void decideApproval(messageId, challengeId, approved)}
                      key={message.id}
                    />
                  ))}
                </AnimatePresence>
                <div ref={scrollAnchor} />
              </div>
            )}
          </div>

          <div className="composer-wrap">
            {health && !health.providerConfigured && (
              <div className="configuration-banner">
                Add <code>GEMINI_API_KEY</code> to the gateway environment to start chatting.
              </div>
            )}
            <form className="composer" onSubmit={onSubmit}>
              <textarea
                ref={textarea}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submit();
                  }
                }}
                rows={1}
                placeholder="Ask about data, features, records, or geospatial processes…"
                aria-label="Message Terra"
                disabled={busy}
              />
              {busy ? (
                <button type="button" className="send-button stop" onClick={() => controller?.abort()}>
                  <Square size={15} fill="currentColor" />
                </button>
              ) : (
                <button type="submit" className="send-button" disabled={!input.trim()}>
                  <Send size={17} />
                </button>
              )}
            </form>
            <div className="composer-meta">
              <span>Enter to send · Shift + Enter for a new line</span>
              <span><ShieldCheck size={12} /> Results come from registered OGC APIs</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
