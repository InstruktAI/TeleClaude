import type { HumanRole } from "@/lib/api/types";

export type ConfigurationAccessPresentation =
  | "full"
  | "hidden"
  | "disabled"
  | "denied";

export interface ConfigurationAccess {
  canOpen: boolean;
  presentation: ConfigurationAccessPresentation;
}

export type ConfigurationSubtabId =
  | "adapters"
  | "people"
  | "notifications"
  | "environment"
  | "validate";

export type ConfigurationActionState = "read_only" | "cli_only_placeholder";

export interface ConfigurationSubtab {
  id: ConfigurationSubtabId;
  label: string;
  readOnly: boolean;
  actionState: ConfigurationActionState;
}

export interface ConfigurationEnvironmentOptions {
  revealedKeys: string[];
}

export interface ConfigurationEnvironmentEntry {
  key: string;
  value: string;
  masked: boolean;
}

const CONFIGURATION_SUBTABS: readonly ConfigurationSubtab[] = [
  {
    id: "adapters",
    label: "Adapters",
    readOnly: true,
    actionState: "read_only",
  },
  {
    id: "people",
    label: "People",
    readOnly: true,
    actionState: "read_only",
  },
  {
    id: "notifications",
    label: "Notifications",
    readOnly: true,
    actionState: "read_only",
  },
  {
    id: "environment",
    label: "Environment",
    readOnly: true,
    actionState: "read_only",
  },
  {
    id: "validate",
    label: "Validate",
    readOnly: true,
    actionState: "cli_only_placeholder",
  },
] as const;

function maskValue(value: string): string {
  return "•".repeat(Math.max(6, Math.min(value.length, 12)));
}

export function resolveConfigurationAccess(
  role?: HumanRole | null,
): ConfigurationAccess {
  if (role === "admin") {
    return {
      canOpen: true,
      presentation: "full",
    };
  }

  return {
    canOpen: false,
    presentation: "denied",
  };
}

export function getConfigurationSubtabs(): ConfigurationSubtab[] {
  return [...CONFIGURATION_SUBTABS];
}

export function buildEnvironmentEntries(
  values: Record<string, string>,
  options: ConfigurationEnvironmentOptions,
): ConfigurationEnvironmentEntry[] {
  const revealedKeys = new Set(options.revealedKeys);

  return Object.entries(values).map(([key, value]) => {
    const masked = !revealedKeys.has(key);
    return {
      key,
      masked,
      value: masked ? maskValue(value) : value,
    };
  });
}
