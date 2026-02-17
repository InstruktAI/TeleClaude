"use client";

import { useState, useCallback } from "react";
import { useComposerRuntime } from "@assistant-ui/react";
import type { InputSection as InputSectionType, InputField } from "@/lib/widgets";

export function InputSectionRenderer({ section }: { section: InputSectionType }) {
  const composer = useComposerRuntime();
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const field of section.fields) {
      initial[field.name] = field.default ?? "";
    }
    return initial;
  });
  const [submitted, setSubmitted] = useState(false);

  const handleChange = useCallback((name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleSubmit = useCallback(() => {
    const parts = Object.entries(values)
      .filter(([, v]) => v.trim() !== "")
      .map(([k, v]) => `${k}: ${v}`);
    const message = `Form submission:\n${parts.join("\n")}`;
    composer.setText(message);
    composer.send();
    setSubmitted(true);
  }, [values, composer]);

  return (
    <div className="space-y-3">
      {section.fields.map((field) => (
        <FieldRenderer
          key={field.name}
          field={field}
          value={values[field.name] ?? ""}
          onChange={handleChange}
          disabled={submitted}
        />
      ))}
      <button
        onClick={handleSubmit}
        disabled={submitted}
        className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {submitted ? "Submitted" : "Submit"}
      </button>
    </div>
  );
}

function FieldRenderer({
  field,
  value,
  onChange,
  disabled,
}: {
  field: InputField;
  value: string;
  onChange: (name: string, value: string) => void;
  disabled: boolean;
}) {
  const baseClass =
    "w-full rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50";

  return (
    <div className={field.width === "half" ? "w-1/2" : "w-full"}>
      <label className="mb-1 block text-sm font-medium">
        {field.label}
        {field.required && <span className="text-destructive"> *</span>}
      </label>
      {field.input === "select" ? (
        <select
          value={value}
          onChange={(e) => onChange(field.name, e.target.value)}
          disabled={disabled || field.disabled}
          className={baseClass}
        >
          <option value="">{field.placeholder || "Select..."}</option>
          {field.options?.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : field.input === "checkbox" ? (
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={value === "true"}
            onChange={(e) => onChange(field.name, String(e.target.checked))}
            disabled={disabled || field.disabled}
            className="h-4 w-4 rounded border"
          />
          <span className="text-sm">{field.helpText}</span>
        </label>
      ) : (
        <input
          type={field.input === "number" ? "number" : field.input === "date" ? "date" : "text"}
          value={value}
          onChange={(e) => onChange(field.name, e.target.value)}
          placeholder={field.placeholder}
          disabled={disabled || field.disabled}
          readOnly={field.readonly}
          className={baseClass}
        />
      )}
      {field.helpText && field.input !== "checkbox" && (
        <p className="mt-0.5 text-xs text-muted-foreground">{field.helpText}</p>
      )}
    </div>
  );
}
