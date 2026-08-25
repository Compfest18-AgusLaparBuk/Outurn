"use client";

import {
  CaretDownIcon as CaretDown,
  EyeIcon as Eye,
  EyeSlashIcon as EyeSlash,
  GithubLogoIcon as GithubLogo,
  GoogleLogoIcon as GoogleLogo,
  AppleLogoIcon as AppleLogo,
  LockKeyIcon as LockKey,
} from "@phosphor-icons/react";
import { Checkbox } from "@cloudflare/kumo/components/checkbox";
import { CloudflareLogo } from "@cloudflare/kumo/components/cloudflare-logo";
import { DropdownMenu } from "@cloudflare/kumo/components/dropdown";
import { Input } from "@cloudflare/kumo/components/input";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { fetchMe, login } from "@/lib/api";
import {
  languageSnapshot,
  setLanguage,
  subscribeToLanguage,
  translate,
  type AppLanguage,
  type LocaleKey,
} from "@/lib/locale";

function GateLogo() {
  return (
    <div className="gate-logo" aria-label="Outurn">
      <CloudflareLogo
        variant="glyph"
        color="color"
        className="gate-logo__mark"
        aria-hidden="true"
      />
      <span className="gate-logo__word">Outurn</span>
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const language = useSyncExternalStore(
    subscribeToLanguage,
    languageSnapshot,
    () => "id" as AppLanguage,
  );
  const t = (key: LocaleKey) => translate(language, key);
  const [nextPath] = useState(() => {
    if (typeof window === "undefined") return "/dashboard";
    const next = new URLSearchParams(window.location.search).get("next");
    return next?.startsWith("/") ? next : "/dashboard";
  });
  const session = useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    retry: false,
  });
  const [email, setEmail] = useState(() =>
    typeof window === "undefined"
      ? ""
      : window.localStorage.getItem("outurn.login.email") || "",
  );
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (session.data) router.replace(nextPath);
  }, [nextPath, router, session.data]);
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const user = await login(email, password);
      if (remember) window.localStorage.setItem("outurn.login.email", email);
      else window.localStorage.removeItem("outurn.login.email");
      router.replace(
        user.must_change_password
          ? `/change-password?next=${encodeURIComponent(nextPath)}`
          : nextPath,
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Akses tidak dapat diverifikasi.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-form-pane" aria-label={t("loginTitle")}>
        <header className="auth-header">
          <GateLogo />
          <div className="auth-mobile-language">
            <DropdownMenu>
              <DropdownMenu.Trigger
                className="auth-language-trigger"
                aria-label={t("language")}
              >
                <span className="auth-language-glyph" aria-hidden="true">
                  ◎
                </span>
                <span>{language === "id" ? "ID" : "EN"}</span>
                <CaretDown size={13} />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="auth-language-menu"
                  align="end"
                  side="bottom"
                  sideOffset={8}
                >
                  <DropdownMenu.Item onClick={() => setLanguage("id")}>
                    Bahasa Indonesia
                  </DropdownMenu.Item>
                  <DropdownMenu.Item onClick={() => setLanguage("en")}>
                    English
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu>
          </div>
        </header>
        <div className="auth-form-wrap">
          <div className="auth-form-heading">
            <h1>{t("loginTitle")}</h1>
          </div>
          <form onSubmit={submit} className="auth-form" noValidate>
            {error && (
              <div role="alert" className="auth-error">
                {error}
              </div>
            )}
            <div
              className="auth-socials"
              aria-label={language === "en" ? "Social sign in" : "Login sosial"}
            >
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  setError(
                    language === "en"
                      ? "Google sign in is not configured for this workspace."
                      : "Login dengan Google belum dikonfigurasi untuk workspace ini.",
                  )
                }
              >
                <span
                  className="auth-social-icon auth-social-icon--google"
                  aria-hidden="true"
                >
                  <GoogleLogo size={16} weight="bold" />
                </span>
                Google
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  setError(
                    language === "en"
                      ? "Apple sign in is not configured for this workspace."
                      : "Login dengan Apple belum dikonfigurasi untuk workspace ini.",
                  )
                }
              >
                <span
                  className="auth-social-icon auth-social-icon--apple"
                  aria-hidden="true"
                >
                  <AppleLogo size={16} weight="fill" />
                </span>
                Apple
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  setError(
                    language === "en"
                      ? "GitHub sign in is not configured for this workspace."
                      : "Login dengan GitHub belum dikonfigurasi untuk workspace ini.",
                  )
                }
              >
                <span
                  className="auth-social-icon auth-social-icon--github"
                  aria-hidden="true"
                >
                  <GithubLogo size={16} weight="fill" />
                </span>
                GitHub
              </Button>
            </div>
            <Button
              type="button"
              variant="secondary"
              icon={LockKey}
              className="auth-sso"
              onClick={() =>
                setError(
                  language === "en"
                    ? "SSO is not configured for this workspace."
                    : "SSO belum dikonfigurasi untuk workspace ini.",
                )
              }
            >
              {language === "en" ? "Continue with SSO" : "Lanjutkan dengan SSO"}
            </Button>
            <div className="auth-divider" aria-hidden="true">
              <span /> <small>{language === "en" ? "OR" : "ATAU"}</small>{" "}
              <span />
            </div>
            <Input
              label={t("email")}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              autoComplete="username"
              placeholder="name@company.com"
              required
            />
            <div className="auth-password">
              <Input
                label={t("password")}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
              />
              <Button
                type="button"
                variant="ghost"
                shape="square"
                size="sm"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={
                  showPassword ? t("hidePassword") : t("showPassword")
                }
              >
                {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
              </Button>
            </div>
            <Checkbox
              className="auth-remember"
              label={t("rememberEmail")}
              checked={remember}
              onCheckedChange={(checked) => setRemember(Boolean(checked))}
            />
            <Button
              type="submit"
              variant="primary"
              className="auth-submit"
              disabled={pending}
            >
              {pending ? t("signingIn") : t("signIn")}
            </Button>
          </form>
          <p className="auth-account">
            {language === "en" ? "Don't have an account?" : "Belum punya akun?"}{" "}
            <a href="/login#signup">
              {language === "en" ? "Sign up" : "Daftar"}
            </a>
          </p>
          <p className="auth-recovery">
            {language === "en" ? (
              <>
                Forgot your <a href="/login#email">email</a> or{" "}
                <a href="/login#password">password</a>?
              </>
            ) : (
              <>
                Lupa <a href="/login#email">email</a> atau{" "}
                <a href="/login#password">password</a>?
              </>
            )}
          </p>
          <p className="auth-support">{t("needAccess")}</p>
          <p className="auth-legal">{t("loginLegal")}</p>
        </div>
      </section>
      <section className="auth-promo" aria-label={t("evidenceWorkspace")}>
        <div className="auth-promo__signal" aria-hidden="true" />
        <div className="auth-promo__top">
          <div className="auth-promo__top-actions">
            <DropdownMenu>
              <DropdownMenu.Trigger
                className="auth-language-trigger"
                aria-label={t("language")}
              >
                <span className="auth-language-glyph" aria-hidden="true">
                  ◎
                </span>
                <span>
                  {language === "id" ? "Bahasa Indonesia" : "English"}
                </span>
                <CaretDown size={13} />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="auth-language-menu"
                  align="end"
                  side="bottom"
                  sideOffset={8}
                >
                  <DropdownMenu.Item onClick={() => setLanguage("id")}>
                    Bahasa Indonesia
                  </DropdownMenu.Item>
                  <DropdownMenu.Item onClick={() => setLanguage("en")}>
                    English
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu>
            <a className="auth-signup" href="/login#signup">
              {language === "en" ? "Sign up" : "Daftar"}
            </a>
          </div>
        </div>
        <div className="auth-promo__copy">
          <p className="auth-promo__eyebrow">{t("loginPanelEyebrow")}</p>
          <h2>{t("loginPanelTitle")}</h2>
          <p>{t("loginPanelBody")}</p>
          <div className="auth-promo__pages" aria-hidden="true">
            <span className="is-active" />
            <span />
            <span />
          </div>
        </div>
      </section>
    </main>
  );
}
