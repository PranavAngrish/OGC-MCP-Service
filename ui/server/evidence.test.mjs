import assert from "node:assert/strict";
import test from "node:test";
import {
  blockedEvidenceAnswer,
  evidenceQualificationNote,
  featureEvidence,
} from "./evidence.mjs";

test("feature evidence accepts complete validated queries", () => {
  const evidence = featureEvidence("ogc_features_query", {
    ok: true,
    data: {
      evidence: {
        safeToAnswer: true,
        complete: true,
        serverId: "features",
        collectionId: "history",
        reasons: [],
      },
    },
  });
  assert.equal(evidence.safeToAnswer, true);
  assert.equal(blockedEvidenceAnswer(evidence), "");
});

test("feature evidence produces a deterministic hard stop for partial queries", () => {
  const evidence = featureEvidence("ogc_features_query", {
    ok: true,
    data: {
      evidence: {
        safeToAnswer: false,
        complete: false,
        serverId: "features",
        collectionId: "history",
        reasons: ["Upstream retrieval is incomplete."],
      },
    },
  });
  const answer = blockedEvidenceAnswer(evidence);
  assert.match(answer, /features \/ history/);
  assert.match(answer, /Upstream retrieval is incomplete/);
  assert.match(answer, /No factual result has been inferred/);
});

test("failed validated queries never default to answerable", () => {
  const evidence = featureEvidence("ogc_features_query", { ok: false });
  assert.equal(evidence.safeToAnswer, false);
  assert.match(blockedEvidenceAnswer(evidence), /returned no evidence record/);
  assert.equal(featureEvidence("ogc_features_get_items", {}), null);
});

test("safe query qualifications become a deterministic scope note", () => {
  const evidence = featureEvidence("ogc_features_query", {
    ok: true,
    data: {
      evidence: {
        safeToAnswer: true,
        complete: true,
        qualifications: ["The subset is an interpretive classification."],
      },
    },
  });
  assert.match(evidenceQualificationNote(evidence), /Evidence scope:/);
  assert.match(evidenceQualificationNote(evidence), /interpretive classification/);
  assert.equal(evidenceQualificationNote({ safeToAnswer: false }), "");
});
