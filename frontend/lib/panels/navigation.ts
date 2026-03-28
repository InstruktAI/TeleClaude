export type PanelId = "sessions" | "preparation" | "configuration" | "jobs";

export interface PanelTab {
  id: PanelId;
  label: string;
  disabled: boolean;
  active: boolean;
}
