"use client";

import { Select as KumoSelect } from "@cloudflare/kumo/components/select";
import { Combobox as KumoCombobox } from "@cloudflare/kumo/components/combobox";
import type { ReactNode } from "react";

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type SelectProps = {
  value?: string | null;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  label?: ReactNode;
  required?: boolean;
  description?: ReactNode;
  error?: string;
};

export function AppCombobox({
  value,
  onValueChange,
  options,
  placeholder,
  label,
  required = false,
  disabled = false,
  className,
  description,
  error,
}: SelectProps & { label?: string; required?: boolean }) {
  const selected = options.find((option) => option.value === (value || ""));
  const items = options.filter((option) => option.value !== "");
  return (
    <div className={join("cf-app-combobox", className)}>
      <KumoCombobox
        items={items}
        value={selected || undefined}
        size="base"
        onValueChange={(next) =>
          onValueChange(
            typeof next === "object" && next !== null && "value" in next
              ? String(next.value)
              : "",
          )
        }
        label={label}
        required={required}
        disabled={disabled}
        description={description}
        error={error}
      >
        <KumoCombobox.TriggerInput
          placeholder={
            placeholder ||
            options.find((option) => option.value === "")?.label ||
            "Pilih opsi"
          }
          aria-label={label || "Pilih opsi"}
        />
        <KumoCombobox.Content>
          <KumoCombobox.List>
            {(item: SelectOption) => (
              <KumoCombobox.Item
                key={item.value}
                value={item}
                disabled={item.disabled}
              >
                {item.label}
              </KumoCombobox.Item>
            )}
          </KumoCombobox.List>
          <KumoCombobox.Empty>Tidak ada opsi yang cocok</KumoCombobox.Empty>
        </KumoCombobox.Content>
      </KumoCombobox>
    </div>
  );
}

type AppSelectProps = SelectProps & { ariaLabel: string };

export function AppSelect({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  disabled = false,
  className,
  label,
  required = false,
  description,
  error,
}: AppSelectProps) {
  const emptyOption = options.find((option) => option.value === "");
  const resolvedPlaceholder = placeholder || emptyOption?.label || "Pilih opsi";

  return (
    <KumoSelect
      aria-label={ariaLabel}
      label={label}
      required={required}
      className={join("cf-app-select", className)}
      disabled={disabled}
      size="base"
      onValueChange={(next) => {
        onValueChange(typeof next === "string" ? next : "");
      }}
      placeholder={resolvedPlaceholder}
      description={description}
      error={error}
      renderValue={(selected) => {
        return (
          options.find((option) => option.value === selected)?.label || selected
        );
      }}
      value={value || null}
    >
      {options.map((option) => (
        <KumoSelect.Option
          disabled={option.disabled}
          key={option.value}
          value={option.value}
        >
          {option.label}
        </KumoSelect.Option>
      ))}
    </KumoSelect>
  );
}

function join(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}
