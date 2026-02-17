"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { useComposerRuntime } from "@assistant-ui/react";
import { useState } from "react";
import { Check } from "lucide-react";

interface QuestionOption {
  label: string;
  description?: string;
}

interface Question {
  question: string;
  header: string;
  options: QuestionOption[];
  multiSelect: boolean;
}

interface AskUserQuestionArgs {
  questions: Question[];
}

type AskUserQuestionResult = Record<string, string>;

export const AskUserQuestionUI = makeAssistantToolUI<
  AskUserQuestionArgs,
  AskUserQuestionResult
>({
  toolName: "AskUserQuestion",
  render: ({ args, status, result }) => {
    if (!args?.questions?.length) return null;

    const isComplete = status.type === "complete";

    return (
      <div className="my-2 space-y-4">
        {args.questions.map((q, qIdx) => (
          <QuestionCard
            key={qIdx}
            question={q}
            isComplete={isComplete}
            result={result}
          />
        ))}
      </div>
    );
  },
});

function QuestionCard({
  question,
  isComplete,
  result,
}: {
  question: Question;
  isComplete: boolean;
  result?: AskUserQuestionResult;
}) {
  const composer = useComposerRuntime();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);

  const disabled = submitted || isComplete;

  const handleSelect = (label: string) => {
    if (disabled) return;

    if (question.multiSelect) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(label)) next.delete(label);
        else next.add(label);
        return next;
      });
    } else {
      // Single select — send immediately
      composer.setText(label);
      composer.send();
      setSelected(new Set([label]));
      setSubmitted(true);
    }
  };

  const handleSubmitMulti = () => {
    if (disabled || selected.size === 0) return;
    const message = Array.from(selected).join(", ");
    composer.setText(message);
    composer.send();
    setSubmitted(true);
  };

  // Determine which options were selected (from result or local state)
  const selectedLabels = isComplete && result
    ? new Set(Object.values(result))
    : selected;

  return (
    <div className="rounded-lg border p-4 space-y-3">
      {question.header && (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {question.header}
        </p>
      )}
      <p className="text-sm font-medium">{question.question}</p>
      <div className="space-y-2">
        {question.options.map((opt) => {
          const isSelected = selectedLabels.has(opt.label);
          return (
            <button
              key={opt.label}
              onClick={() => handleSelect(opt.label)}
              disabled={disabled}
              className={`flex w-full items-start gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors disabled:cursor-default ${
                isSelected
                  ? "border-primary bg-primary/5"
                  : "hover:bg-accent/50 disabled:opacity-60"
              }`}
            >
              <span
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border ${
                  isSelected
                    ? "border-primary bg-primary text-primary-foreground"
                    : ""
                }`}
              >
                {isSelected && <Check className="h-3 w-3" />}
              </span>
              <span>
                <span className="font-medium">{opt.label}</span>
                {opt.description && (
                  <span className="block text-xs text-muted-foreground">
                    {opt.description}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
      {question.multiSelect && !disabled && (
        <button
          onClick={handleSubmitMulti}
          disabled={selected.size === 0}
          className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          Submit
        </button>
      )}
    </div>
  );
}
