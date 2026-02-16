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

function loadConfig(): TeleClaudeGlobalConfig {
  const configPath =
    process.env.TELECLAUDE_CONFIG_PATH ??
    resolve(process.env.HOME ?? "", ".teleclaude", "teleclaude.yml");
  const raw = readFileSync(configPath, "utf-8");
  return parse(raw) as TeleClaudeGlobalConfig;
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
