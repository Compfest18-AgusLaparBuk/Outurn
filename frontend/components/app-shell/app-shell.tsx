"use client";

import {
  CaretDownIcon as CaretDown,
  CaretRightIcon as CaretRight,
  FileTextIcon as FileText,
  GearIcon as Gear,
  HouseIcon as House,
  MagnifyingGlassIcon as MagnifyingGlass,
  PackageIcon as Package,
  SignOutIcon as SignOut,
  SidebarSimpleIcon as SidebarSimple,
  ShieldCheckIcon as ShieldCheck,
  UsersIcon as Users,
  XIcon as X,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Button } from "@/components/ui/button";
import { CloudflareLogo } from "@cloudflare/kumo/components/cloudflare-logo";
import { DropdownMenu } from "@cloudflare/kumo/components/dropdown";
import { Dialog } from "@cloudflare/kumo/components/dialog";
import { Input } from "@cloudflare/kumo/components/input";
import { Loader } from "@cloudflare/kumo/components/loader";
import {
  Sidebar,
  SidebarProvider,
  useSidebar,
} from "@cloudflare/kumo/components/sidebar";
import { hasMinimumRole } from "@/lib/access";
import {
  fetchGlobalSearch,
  fetchMe,
  fetchOrganizations,
  fetchWorkspaceContext,
  logout,
} from "@/lib/api";
import {
  languageSnapshot,
  setLanguage,
  subscribeToLanguage,
  translate,
  type AppLanguage,
  type LocaleKey,
} from "@/lib/locale";

const SIDEBAR_CHANGE_EVENT = "gateguard.sidebar.change";
const ORGANIZATION_CHANGE_EVENT = "gateguard.organization.change";

const NAVIGATION_KEYS: Record<string, LocaleKey> = {
  Home: "home",
  Build: "build",
  Overview: "overview",
  Recents: "recents",
  Operations: "operations",
  "Work queue": "workQueue",
  Shipments: "shipments",
  "New shipment case": "newShipmentCase",
  Documents: "documents",
  Parties: "parties",
  "Products & commodities": "products",
  Transport: "transport",
  "Release decisions": "releaseDecisions",
  Assurance: "assurance",
  "Document checks": "documentChecks",
  Requirements: "requirements",
  "Assurance checks": "assuranceChecks",
  Exceptions: "exceptions",
  "Party screening": "partyScreening",
  "Dangerous goods": "dangerousGoods",
  Observe: "observe",
  Analytics: "analytics",
  Observability: "observability",
  "Activity log": "activityLog",
  Integrate: "integrate",
  Connections: "connections",
  Webhooks: "webhooks",
  "Processing jobs": "processingJobs",
  Governance: "governance",
  "Rule packs": "rulePacks",
  "Reference data": "referenceData",
  Manage: "manage",
  "Workspace settings": "workspaceSettings",
  People: "people",
  "Roles & permissions": "rolesPermissions",
  Security: "security",
  Notifications: "notifications",
};

function localized(language: AppLanguage, value: string) {
  const key = NAVIGATION_KEYS[value];
  return key ? translate(language, key) : value;
}

const groups = [
  {
    label: "Home",
    items: [
      ["/dashboard", "Overview", House, "operator", "home summary"] as const,
      [
        "/shipments",
        "Shipments",
        Package,
        "operator",
        "shipment cases",
      ] as const,
    ],
  },
  {
    label: "Build",
    items: [
      [
        "/shipments/new",
        "New shipment case",
        Package,
        "operator",
        "create shipment intake",
      ] as const,
    ],
  },
  {
    label: "Assurance",
    items: [
      [
        "/reconcile",
        "Document checks",
        FileText,
        "operator",
        "invoice packing list compare",
      ] as const,
      [
        "/exceptions",
        "Exceptions",
        ShieldCheck,
        "operator",
        "resolve shipment discrepancies",
      ] as const,
    ],
  },
] as const;

function subscribeToSidebar(callback: () => void) {
  window.addEventListener(SIDEBAR_CHANGE_EVENT, callback);
  return () => window.removeEventListener(SIDEBAR_CHANGE_EVENT, callback);
}
function getSidebarSnapshot() {
  return window.localStorage.getItem("gateguard.sidebar.collapsed") === "true";
}
function getSidebarServerSnapshot() {
  return false;
}
function subscribeToOrganization(callback: () => void) {
  window.addEventListener(ORGANIZATION_CHANGE_EVENT, callback);
  return () => window.removeEventListener(ORGANIZATION_CHANGE_EVENT, callback);
}
function getOrganizationSnapshot() {
  return window.localStorage.getItem("gateguard.organization") || "";
}
function getOrganizationServerSnapshot() {
  return "";
}
function activeLabel(pathname: string, language: AppLanguage) {
  if (pathname === "/notifications")
    return translate(language, "notifications");
  for (const group of groups) {
    const match = group.items.find(
      ([href]) => pathname === href || pathname.startsWith(`${href}/`),
    );
    if (match) return localized(language, match[1]);
  }
  return translate(language, "overview");
}

function SidebarViewportGuard() {
  const { isMobile, openMobile, setOpenMobile } = useSidebar();
  const initializedMobile = useRef(false);

  useEffect(() => {
    if (!isMobile) {
      initializedMobile.current = false;
      return;
    }
    if (!initializedMobile.current) {
      initializedMobile.current = true;
      if (openMobile) setOpenMobile(false);
    }
  }, [isMobile, openMobile, setOpenMobile]);

  return null;
}

function SidebarControl({
  collapsedLabel,
  expandedLabel,
  className,
}: {
  collapsedLabel: string;
  expandedLabel: string;
  className?: string;
}) {
  const { isMobile, open, openMobile, toggleSidebar } = useSidebar();
  const expanded = isMobile ? openMobile : open;
  return (
    <Button
      variant="ghost"
      shape="square"
      size="base"
      icon={SidebarSimple}
      aria-label={expanded ? expandedLabel : collapsedLabel}
      title={expanded ? expandedLabel : collapsedLabel}
      className={className}
      onClick={toggleSidebar}
    />
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const client = useQueryClient();
  const session = useQuery({ queryKey: ["auth", "me"], queryFn: fetchMe });
  const user = session.data;
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: fetchOrganizations,
    enabled: Boolean(user),
  });
  const collapsed = useSyncExternalStore(
    subscribeToSidebar,
    getSidebarSnapshot,
    getSidebarServerSnapshot,
  );
  const language = useSyncExternalStore(
    subscribeToLanguage,
    languageSnapshot,
    () => "id" as AppLanguage,
  );
  const t = (key: LocaleKey) => translate(language, key);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const deferredSearch = useDeferredValue(search);
  const selectedOrganizationId = useSyncExternalStore(
    subscribeToOrganization,
    getOrganizationSnapshot,
    getOrganizationServerSnapshot,
  );
  const workspaceContext = useQuery({
    queryKey: ["workspace-context", selectedOrganizationId],
    queryFn: fetchWorkspaceContext,
    enabled: Boolean(user),
  });

  const navigation = useMemo(
    () =>
      groups.flatMap((group) =>
        group.items.map(([href, label, Icon, minimum, keywords]) => ({
          href,
          label: localized(language, label),
          Icon,
          minimum,
          keywords,
          group: localized(language, group.label),
        })),
      ),
    [language],
  );
  const workspaceRole = workspaceContext.data?.role || "operator";
  const navResults = navigation.filter(
    (item) =>
      hasMinimumRole(workspaceRole, item.minimum) &&
      [item.label, item.group, item.keywords]
        .join(" ")
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
  );
  const remote = useQuery({
    queryKey: ["global-search", deferredSearch],
    queryFn: () => fetchGlobalSearch(deferredSearch),
    enabled: deferredSearch.trim().length > 1 && searchOpen,
  });
  const remoteResults = useMemo(() => remote.data?.items || [], [remote.data]);
  const resultCount = navResults.length + remoteResults.length;

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
        setSearch("");
        setSelectedIndex(0);
      }
      if (event.key === "Escape") {
        setSearchOpen(false);
      }
      if (!searchOpen) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((value) =>
          Math.min(value + 1, Math.max(resultCount - 1, 0)),
        );
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex((value) => Math.max(value - 1, 0));
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const target =
          navResults[selectedIndex]?.href ||
          remoteResults[selectedIndex - navResults.length]?.href;
        if (target) {
          setSearchOpen(false);
          router.push(target);
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    navResults,
    remoteResults,
    resultCount,
    router,
    searchOpen,
    selectedIndex,
  ]);

  function setSidebarOpen(open: boolean) {
    const next = !open;
    window.localStorage.setItem("gateguard.sidebar.collapsed", String(next));
    window.dispatchEvent(new Event(SIDEBAR_CHANGE_EVENT));
  }
  function openSearch() {
    setSearch("");
    setSelectedIndex(0);
    setSearchOpen(true);
  }
  function selectWorkspace(id: string) {
    window.localStorage.setItem("gateguard.organization", id);
    window.dispatchEvent(new Event(ORGANIZATION_CHANGE_EVENT));
    client.invalidateQueries();
    window.location.reload();
  }
  async function signOut() {
    await logout();
    client.clear();
    router.replace("/login");
  }
  if (session.isPending)
    return (
      <main className="shell-loading" role="status">
        <span className="shell-loading__mark">
          <ShieldCheck size={20} weight="bold" />
        </span>
        <div>
          <strong>Memuat workspace Outurn</strong>
          <p>Menyiapkan data operasional dan akses Anda.</p>
          <Loader size="sm" aria-label="Memuat workspace" />
        </div>
      </main>
    );
  if (!user)
    return (
      <main className="shell-loading shell-loading--error" role="alert">
        <span className="shell-loading__mark">
          <ShieldCheck size={20} weight="bold" />
        </span>
        <div>
          <strong>Sesi tidak tersedia</strong>
          <p>Silakan masuk kembali untuk membuka workspace Outurn.</p>
        </div>
      </main>
    );

  return (
    <div className="console-shell" data-sidebar-collapsed={collapsed}>
      <SidebarProvider
        open={!collapsed}
        onOpenChange={setSidebarOpen}
        collapsible="icon"
        animationDuration={250}
        mobileBreakpoint={768}
        className="console-shell__layout"
      >
        <SidebarViewportGuard />
        <Sidebar
          className="console-sidebar"
          contentClassName="console-sidebar__content"
        >
          <Sidebar.Header className="console-sidebar__brand">
            <span className="console-brand-mark">
              <CloudflareLogo variant="glyph" color="color" aria-hidden="true" />
            </span>
            <span className="console-brand-name">Outurn</span>
            <SidebarControl
              collapsedLabel="Buka navigasi"
              expandedLabel="Perkecil navigasi"
              className="console-sidebar__toggle"
            />
          </Sidebar.Header>
          <div className="workspace-switcher-wrap">
            <DropdownMenu>
              <DropdownMenu.Trigger
                className="console-workspace-switcher"
                aria-label="Ganti ruang kerja"
              >
                <span className="console-context-dot" />
                <span className="console-context-copy">
                  <strong>
                    {String(
                      organizations.data?.items.find(
                        (item) => item.id === selectedOrganizationId,
                      )?.name ||
                        organizations.data?.items[0]?.name ||
                        "Outurn Operations",
                    )}
                  </strong>
                  <small>{t("organizationWorkspace")}</small>
                </span>
                <CaretDown size={14} />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="workspace-menu"
                  align="start"
                  side="bottom"
                  sideOffset={6}
                >
                  {(organizations.data?.items || []).map((item) => (
                    <DropdownMenu.Item
                      key={String(item.id)}
                      onClick={() => selectWorkspace(String(item.id))}
                    >
                      <span>{String(item.name)}</span>
                      <small>{String(item.code)}</small>
                    </DropdownMenu.Item>
                  ))}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu>
          </div>
          <Button
            type="button"
            variant="ghost"
            className="console-search console-search--sidebar"
            icon={MagnifyingGlass}
            onClick={openSearch}
            aria-label={t("searchOuturn")}
          >
            <span className="console-search__label">
              {t("searchOuturn")}
            </span>
            <kbd>Ctrl K</kbd>
          </Button>
          <Sidebar.Content
            className="console-sidebar__nav"
            aria-label="Navigasi Outurn"
          >
            {groups.map((group) => {
              const visible = group.items.filter(([, , , minimum]) =>
                hasMinimumRole(workspaceRole, minimum),
              );
              if (!visible.length) return null;
              return (
                <Sidebar.Group key={group.label} className="console-nav-group">
                  <Sidebar.GroupLabel className="console-sidebar__label">
                    {localized(language, group.label)}
                  </Sidebar.GroupLabel>
                  <Sidebar.Menu>
                    {visible.map(([href, label, Icon]) => {
                      const active =
                        pathname === href || pathname.startsWith(`${href}/`);
                      return (
                        <Sidebar.MenuButton
                          key={href}
                          href={href}
                          active={active}
                          icon={Icon}
                          tooltip={localized(language, label)}
                          aria-current={active ? "page" : undefined}
                        >
                          {localized(language, label)}
                        </Sidebar.MenuButton>
                      );
                    })}
                  </Sidebar.Menu>
                </Sidebar.Group>
              );
            })}
          </Sidebar.Content>
          <Sidebar.Footer className="console-sidebar__footer">
            <DropdownMenu>
              <DropdownMenu.Trigger
                className="console-profile-trigger"
                aria-label="Buka menu profil"
              >
                <span className="console-user-avatar">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </span>
                <span className="console-user-copy">
                  <span className="console-user-name">{user.display_name}</span>
                  <span className="console-user-role">
                    {workspaceRole === "admin"
                      ? "Administrator"
                      : workspaceRole === "supervisor"
                        ? "Peninjau"
                        : "Operator"}
                  </span>
                </span>
                <CaretDown
                  className="console-profile-trigger__chevron"
                  size={14}
                />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="profile-menu"
                  align="start"
                  side="top"
                  sideOffset={8}
                >
                  <DropdownMenu.Label>
                    <strong>{user.display_name}</strong>
                    <span>{user.email}</span>
                  </DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.LinkItem href="/profile" icon={Users}>
                    Profil saya
                  </DropdownMenu.LinkItem>
                  <DropdownMenu.LinkItem href="/change-password" icon={Gear}>
                    Ganti password
                  </DropdownMenu.LinkItem>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item
                    icon={SignOut}
                    onClick={signOut}
                    variant="danger"
                  >
                    {t("signOut")}
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu>
          </Sidebar.Footer>
        </Sidebar>
        <div className="console-main">
          <header className="console-topbar">
            <div className="console-topbar__left">
              <SidebarControl
                collapsedLabel="Buka navigasi"
                expandedLabel="Tutup navigasi"
                className="console-mobile-toggle"
              />
              <div className="console-breadcrumb">
                <span>Outurn</span>
                <CaretRight size={14} />
                <strong>{activeLabel(pathname, language)}</strong>
              </div>
            </div>
            <div className="console-topbar__actions">
              <a className="console-topbar__support" href="/reconcile">
                Bantuan
              </a>
              <DropdownMenu>
                <DropdownMenu.Trigger
                  className="language-picker"
                  aria-label={t("language")}
                >
                  <span>{language === "id" ? "ID" : "EN"}</span>
                  <CaretDown size={13} />
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    className="language-menu"
                    align="end"
                    side="bottom"
                    sideOffset={8}
                  >
                    <DropdownMenu.Item onClick={() => setLanguage("id")}>
                      ID
                    </DropdownMenu.Item>
                    <DropdownMenu.Item onClick={() => setLanguage("en")}>
                      EN
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu>
              <Link
                className="console-topbar__account"
                href="/profile"
                aria-label="Buka profil"
              >
                <span className="console-user-avatar console-user-avatar--small">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </span>
                <span>{user.display_name}</span>
              </Link>
            </div>
          </header>
          <main className="console-content">{children}</main>
          <footer className="console-footer">
                <span>Outurn</span>
            <div>
              <Link href="/settings/security">Status sistem</Link>
              <Link href="/settings">Dokumentasi</Link>
              <Link href="/profile">Privasi</Link>
              <span>
                Build {process.env.NEXT_PUBLIC_APP_VERSION || "2026.08"}
              </span>
            </div>
          </footer>
        </div>
      </SidebarProvider>
      <Dialog.Root open={searchOpen} onOpenChange={setSearchOpen}>
        <Dialog className="search-dialog" size="lg">
          <Dialog.Title className="sr-only">{t("searchTitle")}</Dialog.Title>
          <div className="search-dialog__input">
            <MagnifyingGlass size={18} />
            <Input
              autoFocus
              className="search-dialog__control"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setSelectedIndex(0);
              }}
              placeholder={t("searchPlaceholder")}
            aria-label={t("searchOuturn")}
            />
            <Button
              variant="ghost"
              shape="square"
              size="sm"
              icon={X}
              aria-label={t("closeSearch")}
              onClick={() => setSearchOpen(false)}
            />
          </div>
          <div className="search-dialog__meta">
            <span>
              {search.trim() ? `${resultCount} ${t("results")}` : t("navigate")}
            </span>
            <kbd>{t("escapeToClose")}</kbd>
          </div>
          <div className="search-dialog__results">
            {navResults.map((item, index) => (
              <Button
                key={item.href}
                variant="ghost"
                className={`search-result ${selectedIndex === index ? "is-selected" : ""}`}
                onClick={() => {
                  setSearchOpen(false);
                  router.push(item.href);
                }}
              >
                <item.Icon size={18} />
                <span className="search-result__copy">
                  <span className="search-result__label">{item.label}</span>
                  <span className="search-result__group">{item.group}</span>
                </span>
                <CaretRight size={15} />
              </Button>
            ))}
            {remoteResults.map((item, index) => (
              <Button
                key={`${item.type}-${item.id}`}
                variant="ghost"
                className={`search-result ${selectedIndex === navResults.length + index ? "is-selected" : ""}`}
                onClick={() => {
                  setSearchOpen(false);
                  router.push(item.href);
                }}
              >
                <MagnifyingGlass size={18} />
                <span className="search-result__copy">
                  <span className="search-result__label">{item.label}</span>
                  <span className="search-result__group">
                    {item.description}
                  </span>
                </span>
                <CaretRight size={15} />
              </Button>
            ))}
            {search.trim().length > 1 && !remote.isPending && !resultCount && (
              <div className="search-empty">{t("noResults")}</div>
            )}
          </div>
        </Dialog>
      </Dialog.Root>
    </div>
  );
}
