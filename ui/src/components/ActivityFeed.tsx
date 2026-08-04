import { AnimatePresence, motion } from "motion/react";
import {
  ArrowRight,
  BrainCircuit,
  Check,
  ChevronDown,
  CircleAlert,
  CircleStop,
  Clock3,
  Database,
  LoaderCircle,
  Wrench,
} from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import {
  activityFacts,
  activityDisplayTitle,
  activityNextStep,
  activityOutputSummary,
  activityPanelState,
  activityPurpose,
  activityResultFacts,
  formatDuration,
  technicalJson,
  type ActivityFact,
  type ActivityPanelState,
} from "../lib/activities";
import type { Activity } from "../types";

const stateCopy: Record<ActivityPanelState, string> = {
  working: "Working",
  waiting: "Waiting for you",
  complete: "Complete",
  issues: "Needs attention",
  stopped: "Stopped",
};

const statusCopy: Record<Activity["status"], string> = {
  running: "Running",
  waiting: "Needs your input",
  complete: "Complete",
  error: "Failed",
  cancelled: "Stopped",
};

const iconFor = (activity: Activity) => {
  if (activity.status === "running") {
    return <LoaderCircle aria-hidden="true" className="activity-spinner" size={17} />;
  }
  if (activity.status === "error") return <CircleAlert aria-hidden="true" size={17} />;
  if (activity.status === "cancelled") return <CircleStop aria-hidden="true" size={17} />;
  if (activity.status === "waiting") return <Clock3 aria-hidden="true" size={17} />;
  if (activity.kind === "artifact") return <Database aria-hidden="true" size={17} />;
  if (activity.kind === "reasoning") return <BrainCircuit aria-hidden="true" size={17} />;
  if (activity.kind === "tool") return <Wrench aria-hidden="true" size={17} />;
  return <Check aria-hidden="true" size={17} />;
};

const kindCopy = (activity: Activity) => {
  if (activity.kind === "tool") return "OGC service";
  if (activity.kind === "artifact") return "Output pipeline";
  if (activity.kind === "reasoning") return "Decision summary";
  return "Workflow";
};

function Facts({ facts }: { facts: ActivityFact[] }) {
  if (!facts.length) return <p className="activity-empty-value">No parameters were required.</p>;
  return (
    <dl className="activity-facts">
      {facts.map((fact, index) => (
        <div key={`${fact.label}-${index}`}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}{fact.meta && <small>{fact.meta}</small>}</dd>
        </div>
      ))}
    </dl>
  );
}

function responseTechnicalDetails(activity: Activity): string {
  if (activity.result !== undefined && activity.result !== null) {
    return technicalJson(activity.result);
  }
  if (!activity.resultPreview) return "No technical response body was returned.";
  try {
    return technicalJson(JSON.parse(activity.resultPreview));
  } catch {
    return activity.resultPreview;
  }
}

function ActivityRow({
  activity,
  isCurrent,
}: {
  activity: Activity;
  isCurrent: boolean;
}) {
  const detailsId = useId();
  const [expanded, setExpanded] = useState(
    isCurrent || activity.status === "running" || activity.status === "waiting" || activity.status === "error",
  );
  const inputFacts = useMemo(() => activityFacts(activity.arguments), [activity.arguments]);
  const outputFacts = useMemo(() => activityResultFacts(activity.result), [activity.result]);
  const purpose = activityPurpose(activity);
  const displayTitle = activityDisplayTitle(activity);
  const outputSummary = activity.kind === "tool" ? activityOutputSummary(activity) : "";
  const nextStep = activity.kind === "tool" ? activityNextStep(activity) : undefined;
  const pipelineStep = activity.kind === "artifact";
  const serviceStep = activity.kind === "tool";
  const outputStep = serviceStep || pipelineStep;
  const nextAction = outputStep ? activityNextStep(activity) : nextStep;
  const duration = formatDuration(activity.durationMs);
  const synopsis = outputStep
    ? (activity.status === "running" ? purpose : outputSummary)
    : activity.detail;
  const hasDetails = outputStep
    || activity.detail !== undefined
    || activity.arguments !== undefined
    || activity.resultPreview !== undefined
    || activity.result !== undefined;

  useEffect(() => {
    if (isCurrent || activity.status === "waiting" || activity.status === "error") {
      setExpanded(true);
    } else if (activity.status === "complete" || activity.status === "cancelled") {
      setExpanded(false);
    }
  }, [activity.status, isCurrent]);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={`activity-row activity-${activity.status} ${isCurrent ? "activity-current" : ""}`}
      aria-current={isCurrent ? "step" : undefined}
    >
      <button
        className="activity-summary"
        onClick={() => hasDetails && setExpanded((value) => !value)}
        aria-expanded={hasDetails ? expanded : undefined}
        aria-controls={hasDetails ? detailsId : undefined}
        disabled={!hasDetails}
      >
        <span className="activity-icon">{iconFor(activity)}</span>
        <span className="activity-heading-copy">
          <span className="activity-kind">{kindCopy(activity)}</span>
          <span className="activity-title">{displayTitle}</span>
          {synopsis && <span className="activity-synopsis">{synopsis}</span>}
        </span>
        <span className={`activity-status activity-status-${activity.status}`}>
          {statusCopy[activity.status]}
          {duration && <small>{duration}</small>}
        </span>
        {hasDetails && (
          <ChevronDown
            aria-hidden="true"
            className={expanded ? "chevron-open" : ""}
            size={17}
          />
        )}
      </button>

      <AnimatePresence initial={false}>
        {expanded && hasDetails && (
          <motion.div
            id={detailsId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="activity-details"
          >
            {outputStep ? (
              <>
                <div className="activity-explanation">
                  <span>What Terra is doing</span>
                  <p>{purpose}</p>
                </div>

                <div className="activity-io-grid">
                  <section className="activity-io-card activity-input-card">
                    <span className="activity-block-label">
                      {pipelineStep ? "Artifact context" : "Sent to the service"}
                    </span>
                    <Facts facts={inputFacts} />
                  </section>
                  <section className="activity-io-card activity-output-card">
                    <span className="activity-block-label">
                      {pipelineStep ? "Validation result" : "Received"}
                    </span>
                    <p className="activity-output-headline">{outputSummary}</p>
                    {outputFacts.length > 0 && <Facts facts={outputFacts} />}
                    {activity.warnings?.length ? (
                      <ul className="activity-warnings">
                        {activity.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                      </ul>
                    ) : null}
                  </section>
                </div>

                {nextAction && (
                  <div className="activity-next">
                    <ArrowRight aria-hidden="true" size={15} />
                    <div><span>Next</span><p>{nextAction}</p></div>
                  </div>
                )}

                <details className="activity-technical">
                  <summary>Technical details <span>{pipelineStep ? "ARTIFACT" : "MCP"}</span></summary>
                  <div className="activity-technical-body">
                    <div>
                      <span>{pipelineStep ? "Stage" : "Tool"}</span>
                      <code>{pipelineStep ? activity.artifactStage || "output" : activity.toolName || "Unknown MCP tool"}</code>
                    </div>
                    <div>
                      <span>Request</span>
                      <pre>{technicalJson(activity.arguments ?? {})}</pre>
                    </div>
                    <div>
                      <span>Response</span>
                      <pre>{responseTechnicalDetails(activity)}</pre>
                    </div>
                  </div>
                </details>
              </>
            ) : (
              <div className="activity-explanation">
                <span>{activity.kind === "reasoning" ? "Safe decision summary" : "What is happening"}</span>
                <p>{activity.detail || "This workflow stage completed."}</p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

const isBoilerplateDecision = (activity: Activity) =>
  activity.kind === "reasoning"
  && activity.status === "complete"
  && (
    activity.detail === "I’m identifying the OGC capabilities needed for this request."
    || activity.detail === "I’m reviewing the tool results and deciding whether another MCP step is needed."
  );

export default function ActivityFeed({
  activities,
  active,
}: {
  activities: Activity[];
  active: boolean;
}) {
  const headingId = useId();
  const [now, setNow] = useState(Date.now());
  const visibleActivities = useMemo(
    () => activities.filter((activity) =>
      !(activity.kind === "status" && activity.id.startsWith("synthesize-") && activity.status === "complete")
      && !isBoilerplateDecision(activity)
    ),
    [activities],
  );
  const state = activityPanelState(activities, active);
  const toolCount = activities.filter((activity) => activity.kind === "tool").length;
  const artifactCount = activities.filter((activity) => activity.kind === "artifact").length;
  const currentIndex = visibleActivities.reduce(
    (selected, activity, index) =>
      ["running", "waiting", "error"].includes(activity.status) ? index : selected,
    visibleActivities.length - 1,
  );
  const startedAt = activities
    .map((activity) => activity.startedAt ? Date.parse(activity.startedAt) : Number.NaN)
    .filter(Number.isFinite)
    .sort((left, right) => left - right)[0];
  const totalDuration = Number.isFinite(startedAt)
    ? Math.max(0, now - startedAt)
    : activities.reduce((sum, activity) => sum + (activity.durationMs || 0), 0);

  useEffect(() => {
    if (state !== "working") return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [state]);

  if (!visibleActivities.length) return null;

  return (
    <section className={`activity-panel activity-panel-${state}`} aria-labelledby={headingId}>
      <div className="activity-panel-heading">
        <div>
          <span className="eyebrow">Plan &amp; progress</span>
          <h3 id={headingId}>What Terra is doing</h3>
          <p>Readable decisions, service inputs, and returned results.</p>
        </div>
        <div className="activity-panel-state">
          <span
            className={`live-indicator is-${state}`}
            role={state === "issues" ? "alert" : "status"}
            aria-live="polite"
            aria-atomic="true"
          >
            <i aria-hidden="true" /> {stateCopy[state]}
          </span>
          <small>
            {toolCount} service {toolCount === 1 ? "call" : "calls"}
            {artifactCount > 0 && ` · ${artifactCount} output ${artifactCount === 1 ? "stage" : "stages"}`}
            {totalDuration > 0 && ` · ${formatDuration(totalDuration)}`}
          </small>
        </div>
      </div>

      <ol className="activity-list">
        {visibleActivities.map((activity, index) => (
          <ActivityRow
            activity={activity}
            isCurrent={index === currentIndex}
            key={activity.id}
          />
        ))}
      </ol>

      <p className="reasoning-note">
        “Decision summary” explains the selected action. Private chain-of-thought is not displayed.
      </p>
    </section>
  );
}
