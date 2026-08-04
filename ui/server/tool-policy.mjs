export const INTERNAL_RENDERER_TOOLS = new Set([
  "ogc_proxy_artifact_retrieve",
]);

export const USER_ACTION_TOOLS = new Set([
  "ogc_proxy_confirm_plan",
]);

export function isModelCallableTool(name) {
  return typeof name === "string"
    && !INTERNAL_RENDERER_TOOLS.has(name)
    && !USER_ACTION_TOOLS.has(name);
}

export function modelVisibleMcpTools(tools) {
  return Array.isArray(tools) ? tools.filter((tool) => isModelCallableTool(tool?.name)) : [];
}
