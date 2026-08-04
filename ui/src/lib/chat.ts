import type { StreamEvent } from "../types";

function parseEvent(block: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }

  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
}

export async function streamChat(
  message: string,
  sessionId: string,
  responseId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId, responseId }),
    signal,
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `Chat request failed with status ${response.status}.`);
  }
  if (!response.body) throw new Error("This browser did not provide a streaming response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalSeen = false;

  const dispatch = (block: string) => {
    const parsed = parseEvent(block);
    if (!parsed) return;
    if (parsed.event === "done" || parsed.event === "error") terminalSeen = true;
    onEvent(parsed);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      dispatch(block);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) break;
  }

  // A final SSE event does not have to be followed by a blank line. Process it
  // before deciding whether the gateway closed the stream normally.
  if (buffer.trim()) dispatch(buffer);

  if (!terminalSeen) {
    throw new Error("The chat stream ended before the gateway sent a completion event.");
  }
}

export async function decidePlanApproval(
  sessionId: string,
  challengeId: string,
  approved: boolean,
): Promise<{ decision: "approved" | "rejected"; planId: string }> {
  const response = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(challengeId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    },
  );
  const body = await response.json().catch(() => ({})) as {
    error?: string;
    decision?: "approved" | "rejected";
    planId?: string;
  };
  if (!response.ok || !body.decision || !body.planId) {
    throw new Error(body.error || `Approval request failed with status ${response.status}.`);
  }
  return { decision: body.decision, planId: body.planId };
}

export function subscribeSessionEvents(
  sessionId: string,
  onEvent: (event: StreamEvent) => void,
) {
  const source = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/events`);
  for (const eventName of ["map_data", "job_status"] as const) {
    source.addEventListener(eventName, (event) => {
      try {
        onEvent({
          event: eventName,
          data: JSON.parse((event as MessageEvent<string>).data) as Record<string, unknown>,
        });
      } catch {
        // Ignore a malformed event and allow EventSource to continue/reconnect.
      }
    });
  }
  return () => source.close();
}
