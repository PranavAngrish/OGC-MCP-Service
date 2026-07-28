import { motion } from "motion/react";
import { Bot, CircleAlert } from "lucide-react";
import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../types";
import ActivityFeed from "./ActivityFeed";

const ResultMap = lazy(() => import("./ResultMap"));

export default function MessageBubble({ message }: { message: Message }) {
  const assistant = message.role === "assistant";

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
        {assistant && message.maps?.map((visualization) => (
          <Suspense
            key={visualization.id}
            fallback={<div className="map-loading-card" role="status">Preparing map preview…</div>}
          >
            <ResultMap visualization={visualization} />
          </Suspense>
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
