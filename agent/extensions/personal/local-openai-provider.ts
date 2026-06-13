import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";

type ModelRecord = {
  id: string;
  name?: string;
  context_window?: number;
  max_tokens?: number;
};

const DEFAULT_BASE_URL = "http://localhost:20128/v1";
const DEFAULT_PROVIDER_NAME = "local-openai";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function read9RouterApiKey(): string {
  const dbPath = join(homedir(), ".9router", "db", "data.sqlite");
  if (!existsSync(dbPath)) return "";
  try {
    const { execSync } = require("child_process");
    return execSync(
      `python3 -c "import sqlite3;c=sqlite3.connect('${dbPath}');r=c.execute('SELECT key FROM apiKeys WHERE isActive=1 ORDER BY createdAt DESC').fetchone();print(r[0] if r else '');c.close()"`,
      { encoding: "utf-8", timeout: 3000 }
    ).trim();
  } catch {
    return "";
  }
}

export default async function (pi: ExtensionAPI) {
  const baseUrl = trimTrailingSlash(
    process.env.PI_LOCAL_PROVIDER_BASE_URL?.trim() || DEFAULT_BASE_URL
  );
  const providerName =
    process.env.PI_LOCAL_PROVIDER_NAME?.trim() || DEFAULT_PROVIDER_NAME;
  const apiKey =
    process.env.PI_LOCAL_PROVIDER_API_KEY?.trim() || read9RouterApiKey();

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/models`, {
      headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
      signal: AbortSignal.timeout(5000),
    });
  } catch (err) {
    console.warn(
      `[pi-local-provider] server at ${baseUrl} unreachable (${err instanceof Error ? err.message : err}) — skipping local provider`
    );
    return;
  }

  if (!response.ok) {
    console.warn(
      `[pi-local-provider] model discovery failed: ${response.status} ${response.statusText}`
    );
    return;
  }

  const payload = (await response.json()) as { data?: ModelRecord[] };
  const models = (payload.data ?? []).map((model) => ({
    id: model.id,
    name: model.name ?? model.id,
    reasoning: /\b(reasoning|thinking|think)\b/i.test(model.id),
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: model.context_window ?? 128000,
    maxTokens: model.max_tokens ?? 4096,
  }));

  if (models.length === 0) return;

  pi.registerProvider(providerName, {
    name: "Local OpenAI-Compatible Provider",
    baseUrl,
    apiKey: apiKey || "no-auth-required",
    api: "openai-completions",
    models,
  });
}
