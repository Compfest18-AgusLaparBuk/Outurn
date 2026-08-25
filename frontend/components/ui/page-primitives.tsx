import { LayerCard } from "@cloudflare/kumo/components/layer-card";
import { InputGroup } from "@cloudflare/kumo/components/input-group";
import { Pagination } from "@cloudflare/kumo/components/pagination";
import { Toolbar } from "@cloudflare/kumo/components/toolbar";
import { Empty } from "@cloudflare/kumo/components/empty";
import { Loader } from "@cloudflare/kumo/components/loader";
import { MagnifyingGlassIcon as MagnifyingGlass } from "@phosphor-icons/react";
import type { ReactNode } from "react";

function join(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function CloudflarePageShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={join("cf-page-shell", className)}>{children}</div>;
}

export function FilterBar({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  const visibleLabel =
    label && label.toLowerCase().startsWith("filter") ? "Filter:" : null;
  return (
    <Toolbar className={join("cf-filter-bar", className)} aria-label={label}>
      {visibleLabel && (
        <span className="cf-filter-bar__label">{visibleLabel}</span>
      )}
      {children}
    </Toolbar>
  );
}

export function AppPagination({
  page,
  perPage,
  totalCount,
  setPage,
}: {
  page: number;
  perPage: number;
  totalCount: number;
  setPage: (page: number) => void;
}) {
  if (totalCount <= perPage) return null;
  return (
    <Pagination
      className="cf-pagination"
      page={page}
      perPage={perPage}
      totalCount={totalCount}
      setPage={setPage}
      labels={{
        navigation: "Navigasi halaman",
        firstPage: "Halaman pertama",
        previousPage: "Halaman sebelumnya",
        nextPage: "Halaman berikutnya",
        lastPage: "Halaman terakhir",
        pageNumber: "Nomor halaman",
        pageSize: "Ukuran halaman",
      }}
    >
      <Pagination.Info /> <Pagination.Separator /> <Pagination.Controls />
    </Pagination>
  );
}

export function SearchField({
  value,
  onChange,
  placeholder,
  ariaLabel,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <InputGroup className={join("cf-search-field", className)}>
      <InputGroup.Addon>
        <MagnifyingGlass size={16} aria-hidden="true" />
      </InputGroup.Addon>
      <InputGroup.Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
      />
    </InputGroup>
  );
}

export function DataTableSurface({
  children,
  className,
  title,
  description,
  actions,
}: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <LayerCard className={join("cf-data-surface", className)}>
      {(title || description || actions) && (
        <div className="cf-data-surface__header">
          <div>
            {title && <h2 className="cf-section-title">{title}</h2>}
            {description && (
              <p className="cf-data-surface__description">{description}</p>
            )}
          </div>
          {actions && <div className="cf-data-surface__actions">{actions}</div>}
        </div>
      )}
      {children}
    </LayerCard>
  );
}

export function MainAsideLayout({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={join("cf-main-aside", className)}>{children}</div>;
}

export function MetricsHeader({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <section className={join("cf-metric-strip", className)} aria-label={label}>
      {children}
    </section>
  );
}

export function ChartSurface({
  children,
  className,
  title,
  description,
  actions,
}: {
  children: ReactNode;
  className?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <DataTableSurface
      className={join("cf-chart-surface", className)}
      title={title}
      description={description}
      actions={actions}
    >
      {children}
    </DataTableSurface>
  );
}

export function SettingSection({
  children,
  className,
  title,
  description,
}: {
  children: ReactNode;
  className?: string;
  title: ReactNode;
  description?: ReactNode;
}) {
  return (
    <section className={join("cf-setting-section", className)}>
      <div>
        <h2 className="cf-section-title">{title}</h2>
        {description && (
          <p className="cf-setting-section__description">{description}</p>
        )}
      </div>
      <div className="cf-setting-section__content">{children}</div>
    </section>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <Empty
      size="sm"
      className={join("cf-empty-state", className)}
      icon={icon}
      title={typeof title === "string" ? title : String(title)}
      description={
        typeof description === "string"
          ? description
          : description
            ? String(description)
            : undefined
      }
      contents={
        action ? (
          <div className="cf-empty-state__action">{action}</div>
        ) : undefined
      }
    />
  );
}

export function LoadingState({
  label = "Memuat…",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div className={join("cf-loading-state", className)} role="status">
      <Loader size="sm" aria-label={label} />
      <span>{label}</span>
    </div>
  );
}
