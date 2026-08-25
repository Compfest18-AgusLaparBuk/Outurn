import { Textarea } from "@cloudflare/kumo/components/input";
import { forwardRef, type TextareaHTMLAttributes } from "react";

function join(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

type AppTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: string;
  description?: string;
  error?: string;
};

export const AppTextarea = forwardRef<HTMLTextAreaElement, AppTextareaProps>(
  function AppTextarea(
    { label, description, error, className = "", id, ...props },
    ref,
  ) {
    const controlId =
      id || `textarea-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    return (
      <div className={join("app-textarea", className)}>
        <Textarea
          ref={ref}
          id={controlId}
          className="app-textarea__control"
          label={label}
          description={description}
          error={error}
          variant={error ? "error" : "default"}
          {...props}
        />
      </div>
    );
  },
);
