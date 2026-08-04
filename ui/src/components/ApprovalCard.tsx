import { Ban, Check, ShieldCheck } from "lucide-react";
import type { ApprovalRequest } from "../types";

type Props = {
  request: ApprovalRequest;
  disabled?: boolean;
  onDecide: (challengeId: string, approved: boolean) => void;
};

const formatted = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[Unable to display this value]";
  }
};

export default function ApprovalCard({ request, disabled, onDecide }: Props) {
  const decided = ["approved", "rejected"].includes(request.status);
  const submitting = request.status === "submitting";
  return (
    <section className={`approval-card is-${request.status}`} aria-label={`Approval for plan ${request.planId}`}>
      <header>
        <span><ShieldCheck size={15} aria-hidden="true" /> Human approval required</span>
        <strong>{request.planId}</strong>
      </header>
      <p>
        Review the exact process request below. Approval applies only to this
        version; any later change requires a new review.
      </p>
      <details open>
        <summary>Exact execute request</summary>
        <pre>{formatted(request.executeRequest)}</pre>
      </details>
      {request.inputContext && Object.keys(request.inputContext as object).length > 0 ? (
        <details>
          <summary>Input provenance, units, and assumptions</summary>
          <pre>{formatted(request.inputContext)}</pre>
        </details>
      ) : null}
      <div className="approval-card__meta">
        <span>Server: {request.serverId || "configured default"}</span>
        <span>Request fingerprint: {request.digest.slice(0, 12)}…</span>
      </div>
      {request.error ? <div className="approval-card__error" role="alert">{request.error}</div> : null}
      {decided ? (
        <div className="approval-card__decision" role="status">
          {request.status === "approved"
            ? <><Check size={16} /> Approved by you</>
            : <><Ban size={16} /> Rejected by you</>}
        </div>
      ) : (
        <div className="approval-card__actions">
          <button
            type="button"
            className="approval-reject"
            disabled={disabled || submitting}
            onClick={() => onDecide(request.challengeId, false)}
          >
            <Ban size={15} /> Reject
          </button>
          <button
            type="button"
            className="approval-approve"
            disabled={disabled || submitting}
            onClick={() => onDecide(request.challengeId, true)}
          >
            <Check size={15} /> {submitting ? "Recording…" : "Approve exact request"}
          </button>
        </div>
      )}
    </section>
  );
}
