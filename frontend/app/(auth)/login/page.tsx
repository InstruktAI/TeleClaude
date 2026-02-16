"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";

interface Person {
  name: string;
  email?: string;
  role: string;
}

function LoginForm() {
  const searchParams = useSearchParams();
  const isVerify = searchParams?.get("verify") === "1";
  const errorParam = searchParams?.get("error");

  const [people, setPeople] = useState<Person[]>([]);
  const [selectedEmail, setSelectedEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"select" | "verify">(
    isVerify ? "verify" : "select",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(errorParam ? "Authentication failed" : "");

  useEffect(() => {
    fetch("/api/people")
      .then((r) => {
        if (r.ok) return r.json();
        return [];
      })
      .then((data: Person[]) => setPeople(data))
      .catch(() => setPeople([]));
  }, []);

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedEmail) return;
    setLoading(true);
    setError("");

    try {
      const csrfRes = await fetch("/api/auth/csrf");
      const { csrfToken } = await csrfRes.json();

      const res = await fetch("/api/auth/signin/nodemailer", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          email: selectedEmail,
          csrfToken,
          callbackUrl: "/",
        }),
        redirect: "manual",
      });

      if (res.ok || res.type === "opaqueredirect" || res.status === 302) {
        setStep("verify");
      } else {
        setError("Failed to send verification code");
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }

  function handleCodeSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!code || code.length !== 6) return;

    const callbackUrl = new URL(
      "/api/auth/callback/nodemailer",
      window.location.origin,
    );
    callbackUrl.searchParams.set("token", code);
    callbackUrl.searchParams.set("email", selectedEmail);
    callbackUrl.searchParams.set("callbackUrl", "/");
    window.location.href = callbackUrl.toString();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-lg border p-8">
        <div className="text-center">
          <h1 className="text-2xl font-bold">TeleClaude</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to continue</p>
        </div>

        {error && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {step === "select" ? (
          <form onSubmit={handleEmailSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="person-select"
                className="mb-1 block text-sm font-medium"
              >
                Who are you?
              </label>
              <select
                id="person-select"
                value={selectedEmail}
                onChange={(e) => setSelectedEmail(e.target.value)}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                required
              >
                <option value="">Select your name...</option>
                {people
                  .filter((p) => p.email)
                  .map((p) => (
                    <option key={p.email} value={p.email!}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={!selectedEmail || loading}
              className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {loading ? "Sending code..." : "Send verification code"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleCodeSubmit} className="space-y-4">
            <p className="text-center text-sm text-muted-foreground">
              Enter the 6-digit code sent to{" "}
              <strong>{selectedEmail}</strong>
            </p>

            <div>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) =>
                  setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
                placeholder="000000"
                className="w-full rounded-md border bg-background px-3 py-3 text-center text-2xl tracking-[0.3em] focus:outline-none focus:ring-2 focus:ring-ring"
                autoFocus
                required
              />
            </div>

            <button
              type="submit"
              disabled={code.length !== 6}
              className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Verify
            </button>

            <button
              type="button"
              onClick={() => {
                setStep("select");
                setCode("");
                setError("");
              }}
              className="w-full text-sm text-muted-foreground hover:underline"
            >
              Back
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
