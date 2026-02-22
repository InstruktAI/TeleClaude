import { readFileSync } from "fs";
import { resolve } from "path";
import { parse } from "yaml";

export interface Person {
  name: string;
  email?: string;
  username?: string;
  role: "admin" | "member" | "contributor" | "newcomer";
}

interface TeleClaudeGlobalConfig {
  people?: Person[];
}

let cachedPeople: Person[] | null = null;
let cacheTimestamp = 0;
const CACHE_TTL_MS = 60_000;

function expandHome(p: string): string {
  if (p.startsWith("~/")) return resolve(process.env.HOME ?? "", p.slice(2));
  return p;
}

function loadConfig(): TeleClaudeGlobalConfig {
  const configPath = expandHome(
    process.env.TELECLAUDE_CONFIG_PATH ??
    resolve(process.env.HOME ?? "", ".teleclaude", "teleclaude.yml"),
  );

  try {
    const raw = readFileSync(configPath, "utf-8");
    return parse(raw) as TeleClaudeGlobalConfig;
  } catch (err) {
    const error = err as NodeJS.ErrnoException;
    console.error(`[people] Failed to load config from ${configPath}:`, error.message);

    if (error.code === "ENOENT") {
      throw new Error(`TeleClaude config file not found at ${configPath}`);
    } else if (error.code === "EACCES") {
      throw new Error(`Permission denied reading config file at ${configPath}`);
    } else {
      throw new Error(`Failed to parse TeleClaude config: ${error.message}`);
    }
  }
}

export function getPeople(): Person[] {
  const now = Date.now();
  if (cachedPeople && now - cacheTimestamp < CACHE_TTL_MS) {
    return cachedPeople;
  }
  const config = loadConfig();
  cachedPeople = (config.people ?? []).map((p) => ({
    name: p.name,
    email: p.email,
    username: p.username,
    role: p.role ?? "member",
  }));
  cacheTimestamp = now;
  return cachedPeople;
}

export function findPersonByEmail(email: string): Person | undefined {
  return getPeople().find((p) => p.email?.toLowerCase() === email.toLowerCase());
}
