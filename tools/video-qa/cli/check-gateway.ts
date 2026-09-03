/**
 * check-gateway — is the Vercel AI Gateway configured for this engine?
 *
 *   npm run qa:check
 *
 * Prints whether AI_GATEWAY_API_KEY is present (never the value), whether the
 * configured Layer-3 model and transcription model exist on the gateway, and — for
 * the L3 model — whether it is tagged for file input, which video review needs.
 * The model list is public (`GET /v1/models`), so this works before a key is set.
 * Exit 0 when everything the engine will call is in place; 1 otherwise.
 */
import "../src/env";
import { GATEWAY_BASE, gatewayKey, listGatewayModels, qaModel, transcribeModel } from "../src/gateway";

async function main() {
  let ok = true;
  const key = gatewayKey();
  console.log(`gateway: ${GATEWAY_BASE}`);
  console.log(key ? "AI_GATEWAY_API_KEY: present" : "AI_GATEWAY_API_KEY: MISSING — L3 and the cloud transcriber will skip");
  if (!key) ok = false;

  let models: Awaited<ReturnType<typeof listGatewayModels>> = [];
  try {
    models = await listGatewayModels();
  } catch (e) {
    console.log(`could not list models: ${(e as Error).message}`);
    process.exit(1);
  }
  const byId = new Map(models.map((m) => [m.id, m]));

  const l3 = byId.get(qaModel());
  if (!l3) {
    ok = false;
    console.log(`VIDEO_QA_MODEL=${qaModel()}: NOT on the gateway. Google video-capable ids currently listed:`);
    for (const m of models.filter((m) => m.id.startsWith("google/") && (m.tags ?? []).includes("file-input"))) {
      console.log(`  ${m.id}`);
    }
  } else {
    const fileInput = (l3.tags ?? []).includes("file-input");
    console.log(`VIDEO_QA_MODEL=${l3.id}: ok${fileInput ? " (file-input)" : " — WARNING: not tagged file-input; video review may be rejected"}`);
    if (!fileInput) ok = false;
  }

  const tr = byId.get(transcribeModel());
  console.log(
    tr
      ? `VIDEO_QA_TRANSCRIBE_MODEL=${tr.id}: ok`
      : `VIDEO_QA_TRANSCRIBE_MODEL=${transcribeModel()}: NOT on the gateway (transcription models: ${models
          .filter((m) => m.type === "transcription")
          .map((m) => m.id)
          .join(", ") || "none listed"})`
  );
  if (!tr) ok = false;

  console.log(ok ? "READY" : "NOT READY");
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(`[qa:check] fatal: ${(e as Error).message}`);
  process.exit(1);
});
