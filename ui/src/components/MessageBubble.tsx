import { motion } from "motion/react";
import { Bot, CircleAlert } from "lucide-react";
import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { manifestHasReadyMap, mapVisualizationHasDrawableLayer } from "../lib/outputs";
import type { Message } from "../types";
import ActivityFeed from "./ActivityFeed";
import ApprovalCard from "./ApprovalCard";

const ResultMap = lazy(() => import("./ResultMap"));
const OutputPanel = lazy(() => import("./OutputPanel"));

export default function MessageBubble({
  message,
  onApprovalDecision,
}: {
  message: Message;
  onApprovalDecision?: (messageId: string, challengeId: string, approved: boolean) => void;
}) {
  const assistant = message.role === "assistant";
  const manifestOwnsMap = manifestHasReadyMap(message.outputManifests);
  const legacyMaps = manifestOwnsMap
    ? []
    : (message.maps || []).filter((visualization) => mapVisualizationHasDrawableLayer(visualization));
  const unusableLegacyMaps = manifestOwnsMap
    ? []
    : (message.maps || []).filter((visualization) => !mapVisualizationHasDrawableLayer(visualization));

  return (
    <motion.article
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`message ${message.role}`}
    >
      {assistant && (
        <div className="assistant-avatar" aria-hidden="true">
          <Bot size={17} />
        </div>
      )}
      <div className="message-body">
        {assistant && <span className="message-author">Terra</span>}
        {assistant && message.activities && message.activities.length > 0 && (
          <ActivityFeed
            activities={message.activities}
            active={Boolean(message.pending || message.activities.some((activity) => activity.status === "running"))}
          />
        )}
        {message.content && (
          <div className="message-content markdown-body">
            {assistant ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            ) : (
              <p>{message.content}</p>
            )}
          </div>
        )}
        {assistant && message.approvalRequests?.map((request) => (
          <ApprovalCard
            request={request}
            disabled={message.pending}
            onDecide={(challengeId, approved) =>
              onApprovalDecision?.(message.id, challengeId, approved)}
            key={request.challengeId}
          />
        ))}
        {assistant && Boolean(message.outputManifests?.length) && (
          <Suspense fallback={<div className="map-loading-card" role="status">Preparing output presentations…</div>}>
            <OutputPanel manifests={message.outputManifests || []} />
          </Suspense>
        )}
        {assistant && legacyMaps.map((visualization) => (
          <Suspense
            key={visualization.id}
            fallback={<div className="map-loading-card" role="status">Preparing map preview…</div>}
          >
            <ResultMap visualization={visualization} />
          </Suspense>
        ))}
        {assistant && unusableLegacyMaps.map((visualization) => (
          <div className="legacy-map-fallback" role="status" key={visualization.id}>
            <CircleAlert size={17} aria-hidden="true" />
            <div>
              <strong>Map preview not created</strong>
              <p>
                “{visualization.title}” did not contain a validated drawable result layer.
                Its output has not been presented as an empty map.
              </p>
            </div>
          </div>
        ))}
        {assistant && message.pending && !message.content && (
          <div className="answer-placeholder">
            <span /> <span /> <span />
          </div>
        )}
        {message.error && (
          <div className="message-error"><CircleAlert size={16} /> {message.error}</div>
        )}
      </div>
    </motion.article>
  );
}
