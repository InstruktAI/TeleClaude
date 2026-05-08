import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { request, type FullConfig } from "@playwright/test";

interface OtpRecord {
  email: string;
  token: string;
  url: string;
  ts: number;
}

const DEFAULT_BASE_URL = "http://localhost:3000";
const POLL_INTERVAL_MS = 250;
const POLL_TIMEOUT_MS = 60_000;
const OTP_DIR = tmpdir();

function otpFilePath(email: string): string {
  return join(OTP_DIR, `teleclaude-e2e-otp-${encodeURIComponent(email)}.json`);
}

function readOtp(email: string, sinceTs: number): OtpRecord | null {
  const path = otpFilePath(email);
  if (!existsSync(path)) return null;
  const raw = readFileSync(path, { encoding: "utf8" });
  const record = JSON.parse(raw) as OtpRecord;
  if (record.ts < sinceTs) return null;
  return record;
}

async function waitForOtp(email: string, sinceTs: number): Promise<OtpRecord> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const otp = readOtp(email, sinceTs);
    if (otp) return otp;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error(
    `e2e/global-setup: timed out after ${POLL_TIMEOUT_MS}ms waiting for OTP file for ${email}.`,
  );
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const email = process.env.TEST_EMAIL ?? "tester@instrukt.ai";
  const baseURL =
    config.projects[0]?.use.baseURL?.toString() ?? DEFAULT_BASE_URL;
  const storageStatePath =
    config.projects[0]?.use.storageState?.toString() ?? "e2e/.auth/state.json";

  const otpPathBefore = otpFilePath(email);
  if (existsSync(otpPathBefore)) {
    unlinkSync(otpPathBefore);
  }
  const sinceTs = Date.now();

  const context = await request.newContext({ baseURL });

  const csrfRes = await context.get("/api/auth/csrf");
  if (!csrfRes.ok()) {
    throw new Error(
      `e2e/global-setup: /api/auth/csrf returned ${csrfRes.status()} (${await csrfRes.text()}).`,
    );
  }
  const { csrfToken } = (await csrfRes.json()) as { csrfToken: string };

  const signinRes = await context.post("/api/auth/signin/nodemailer", {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    form: {
      email,
      csrfToken,
      callbackUrl: "/",
    },
    maxRedirects: 0,
    failOnStatusCode: false,
  });
  if (signinRes.status() >= 400) {
    throw new Error(
      `e2e/global-setup: signin returned ${signinRes.status()} (${await signinRes.text()}).`,
    );
  }

  const otp = await waitForOtp(email, sinceTs);

  // The verification URL written by NextAuth carries the hashed token as the
  // querystring `token` param. Hitting it lands an authenticated session
  // cookie on the request context — exactly what the browser's GET /callback
  // does when the user submits the 6-digit code in the login form.
  const verifyRes = await context.get(otp.url, {
    maxRedirects: 5,
    failOnStatusCode: false,
  });
  if (verifyRes.status() >= 400) {
    throw new Error(
      `e2e/global-setup: callback returned ${verifyRes.status()} (${await verifyRes.text()}).`,
    );
  }

  await context.storageState({ path: storageStatePath });
  await context.dispose();
}
