function boundedReasons(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => typeof item === "string" && item.trim())
    .map((item) => item.trim().slice(0, 500))
    .slice(0, 8);
}

/** Extract the authoritative answer policy from a structured feature query. */
export function featureEvidence(toolName, payload) {
  if (toolName !== "ogc_features_query") return null;
  const evidence = payload?.data?.evidence;
  if (payload?.ok === false || !evidence || typeof evidence !== "object") {
    return {
      safeToAnswer: false,
      reasons: ["The validated feature query failed or returned no evidence record."],
    };
  }
  return {
    safeToAnswer: evidence.safeToAnswer === true,
    complete: evidence.complete === true,
    serverId: typeof evidence.serverId === "string" ? evidence.serverId.slice(0, 200) : "",
    collectionId: typeof evidence.collectionId === "string" ? evidence.collectionId.slice(0, 200) : "",
    reasons: boundedReasons(evidence.reasons),
    qualifications: boundedReasons(evidence.qualifications),
  };
}

/** Return a deterministic hard-stop answer when the latest evidence is incomplete. */
export function blockedEvidenceAnswer(evidence) {
  if (!evidence || evidence.safeToAnswer === true) return "";
  const source = [evidence.serverId, evidence.collectionId].filter(Boolean).join(" / ");
  const reasons = evidence.reasons?.length
    ? evidence.reasons.map((reason) => `- ${reason}`).join("\n")
    : "- The query did not establish complete, answerable evidence.";
  return [
    `I could not produce a verified answer${source ? ` from ${source}` : ""}.`,
    "",
    reasons,
    "",
    "No factual result has been inferred from incomplete feature data. Please refine the filters, region, properties, or retrieval limits and try again.",
  ].join("\n");
}

/** Always surface authoritative scope qualifications for the latest safe query. */
export function evidenceQualificationNote(evidence) {
  if (!evidence?.safeToAnswer || !evidence.qualifications?.length) return "";
  return [
    "Evidence scope:",
    ...evidence.qualifications.map((qualification) => `- ${qualification}`),
  ].join("\n");
}
