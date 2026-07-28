import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import path from "node:path";
import { fileURLToPath } from "node:url";

const serverDirectory = path.dirname(fileURLToPath(import.meta.url));
const uiDirectory = path.resolve(serverDirectory, "..");
const repositoryRoot = path.resolve(uiDirectory, "..");
const DEFAULT_TOOL_TIMEOUT_MS = 3 * 60 * 1_000;
const MIN_TOOL_TIMEOUT_MS = 10 * 1_000;
const MAX_TOOL_TIMEOUT_MS = 15 * 60 * 1_000;

const resolveFromUi = (candidate, fallback) => {
  const selected = candidate || fallback;
  return path.isAbsolute(selected) ? selected : path.resolve(uiDirectory, selected);
};

export function resolveMcpToolTimeoutMs(value) {
  if (value === undefined || value === null || String(value).trim() === "") {
    return DEFAULT_TOOL_TIMEOUT_MS;
  }
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds)) return DEFAULT_TOOL_TIMEOUT_MS;
  return Math.min(
    MAX_TOOL_TIMEOUT_MS,
    Math.max(MIN_TOOL_TIMEOUT_MS, Math.round(milliseconds)),
  );
}

export function mcpToolRequestOptions(options = {}, configuredTimeout) {
  const requestOptions = { ...options };
  if (requestOptions.timeout === undefined || requestOptions.timeout === null) {
    requestOptions.timeout = resolveMcpToolTimeoutMs(
      configuredTimeout ?? process.env.OGC_MCP_TOOL_TIMEOUT_MS,
    );
  }
  return requestOptions;
}

let clientPromise;

async function connectClient() {
  const python = resolveFromUi(
    process.env.OGC_MCP_PYTHON,
    path.join(repositoryRoot, "venv", "bin", "python"),
  );
  const configPath = resolveFromUi(
    process.env.OGC_MCP_CONFIG,
    path.join(repositoryRoot, "standardized_server", "config.example.json"),
  );

  const transport = new StdioClientTransport({
    command: python,
    args: [
      "-m",
      "ogc_mcp_reference",
      "--config",
      configPath,
      "--transport",
      "stdio",
    ],
    cwd: repositoryRoot,
    env: {
      ...process.env,
      PYTHONPATH: path.join(repositoryRoot, "standardized_server", "src"),
    },
    stderr: "inherit",
  });

  const client = new Client({ name: "terra-console", version: "0.1.0" });
  await client.connect(transport);
  return client;
}

export async function getMcpClient() {
  if (!clientPromise) {
    clientPromise = connectClient().catch((error) => {
      clientPromise = undefined;
      throw error;
    });
  }
  return clientPromise;
}

export async function listMcpTools() {
  const client = await getMcpClient();
  const { tools } = await client.listTools();
  return tools;
}

export async function callMcpTool(name, args, options = {}) {
  const client = await getMcpClient();
  return client.callTool(
    { name, arguments: args },
    undefined,
    mcpToolRequestOptions(options),
  );
}
