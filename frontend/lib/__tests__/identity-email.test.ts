import { beforeEach, describe, expect, it, vi } from "vitest";

const { sendMailMock, createTransportMock } = vi.hoisted(() => {
  const sendMailMock = vi.fn();
  const createTransportMock = vi.fn(() => ({
    sendMail: sendMailMock,
  }));
  return { sendMailMock, createTransportMock };
});

vi.mock("nodemailer", () => ({
  createTransport: createTransportMock,
}));

import { sendVerificationRequest } from "@/lib/identity/email";

describe("sendVerificationRequest", () => {
  const consoleLogSpy = vi.spyOn(console, "log").mockImplementation(() => {});

  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllEnvs();
    sendMailMock.mockResolvedValue({
      rejected: [],
      pending: [],
    });
  });

  it("logs the OTP and skips email delivery in development", async () => {
    vi.stubEnv("NODE_ENV", "development");

    await sendVerificationRequest({
      identifier: "tester@instrukt.ai",
      token: "123456",
      expires: new Date(),
      url: "http://localhost:3000",
      provider: {},
      theme: null,
      request: new Request("http://localhost:3000"),
    });

    expect(consoleLogSpy).toHaveBeenCalledWith(
      "[AUTH DEV] Verification code for tester@instrukt.ai: 123456",
    );
    expect(createTransportMock).not.toHaveBeenCalled();
    expect(sendMailMock).not.toHaveBeenCalled();
  });

  it("sends the OTP email outside development mode", async () => {
    vi.stubEnv("NODE_ENV", "production");

    await sendVerificationRequest({
      identifier: "tester@instrukt.ai",
      token: "654321",
      expires: new Date(),
      url: "http://localhost:3000",
      provider: {
        server: { host: "smtp.example.com" },
        from: "TeleClaude <app@instrukt.ai>",
      },
      theme: null,
      request: new Request("http://localhost:3000"),
    });

    expect(consoleLogSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("654321"),
    );
    expect(createTransportMock).toHaveBeenCalledWith({
      host: "smtp.example.com",
    });
    expect(sendMailMock).toHaveBeenCalledWith(
      expect.objectContaining({
        to: "tester@instrukt.ai",
        from: "TeleClaude <app@instrukt.ai>",
        subject: "Your TeleClaude login code",
      }),
    );
  });
});
