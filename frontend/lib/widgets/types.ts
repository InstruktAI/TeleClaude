// Widget expression format types — matches the MCP tool JSON Schema.

// --- Section-level common fields ---

export type SectionVariant =
  | "default"
  | "info"
  | "success"
  | "warning"
  | "error"
  | "muted";

interface SectionBase {
  label?: string;
  variant?: SectionVariant;
  id?: string;
}

// --- Per-section types ---

export interface TextSection extends SectionBase {
  type: "text";
  content: string;
}

export interface InputField {
  name: string;
  label: string;
  input: "text" | "select" | "checkbox" | "number" | "date";
  options?: string[];
  required?: boolean;
  placeholder?: string;
  default?: string;
  helpText?: string;
  disabled?: boolean;
  readonly?: boolean;
  width?: "half" | "full";
  validation?: {
    min?: number;
    max?: number;
    pattern?: string;
    message?: string;
  };
}

export interface InputSection extends SectionBase {
  type: "input";
  fields: InputField[];
}

export interface Button {
  label: string;
  action: string;
  style?: "primary" | "secondary" | "destructive";
  icon?: string;
  disabled?: boolean;
  confirm?: string;
}

export interface ActionsSection extends SectionBase {
  type: "actions";
  buttons: Button[];
  layout?: "horizontal" | "vertical";
}

export interface ImageSection extends SectionBase {
  type: "image";
  src: string;
  alt?: string;
  width?: number;
  height?: number;
  caption?: string;
}

export interface TableSection extends SectionBase {
  type: "table";
  headers: string[];
  rows: (string | number)[][];
  caption?: string;
  sortable?: boolean;
  filterable?: boolean;
  maxRows?: number;
}

export interface FileSection extends SectionBase {
  type: "file";
  path: string;
  label?: string;
  size?: number;
  mime?: string;
  preview?: boolean;
}

export interface CodeSection extends SectionBase {
  type: "code";
  content: string;
  language?: string;
  title?: string;
  collapsible?: boolean;
  lineNumbers?: boolean;
}

export interface DividerSection extends SectionBase {
  type: "divider";
}

// --- Discriminated union ---

export type Section =
  | TextSection
  | InputSection
  | ActionsSection
  | ImageSection
  | TableSection
  | FileSection
  | CodeSection
  | DividerSection;

// --- Expression-level types ---

export type WidgetStatus = "info" | "success" | "warning" | "error";

export interface WidgetExpression {
  name?: string;
  title?: string;
  description?: string;
  hints?: Record<string, unknown>;
  sections: Section[];
  footer?: string;
  status?: WidgetStatus;
}

// --- MCP tool args/result ---

export interface RenderWidgetArgs {
  data: WidgetExpression;
}

export interface RenderWidgetResult {
  rendered: boolean;
  summary: string;
}
