import { createTransport } from "nodemailer";

interface SendVerificationRequestParams {
  identifier: string;
  token: string;
  expires: Date;
  url: string;
  provider: {
    server?: unknown;
    from?: string;
  };
  theme: unknown;
  request: Request;
}

export async function sendVerificationRequest(
  params: SendVerificationRequestParams,
) {
  const { identifier: email, token, provider } = params;
  console.log(`[AUTH] Sending verification code ${token} to ${email}`);
  if (!provider.server) throw new Error("SMTP server not configured");

  const transport = createTransport(provider.server as object);

  const result = await transport.sendMail({
    to: email,
    from: provider.from,
    subject: "Your TeleClaude login code",
    text: `Your verification code is: ${token}\n\nThis code expires in 3 minutes.\n\nIf you did not request this code, please ignore this email.`,
    html: `
      <body style="background:#f4f4f5;margin:0;padding:40px 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;margin:0 auto;">
          <tr>
            <td style="background:#ffffff;border-radius:8px;padding:40px;text-align:center;">
              <h1 style="color:#18181b;font-size:24px;margin:0 0 8px;">TeleClaude</h1>
              <p style="color:#71717a;font-size:14px;margin:0 0 32px;">Enter this code to sign in</p>
              <div style="background:#f4f4f5;border-radius:8px;padding:20px;margin:0 0 32px;">
                <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#18181b;">${token}</span>
              </div>
              <p style="color:#a1a1aa;font-size:12px;margin:0;">
                This code expires in 3 minutes.<br/>
                If you did not request this, ignore this email.
              </p>
            </td>
          </tr>
        </table>
      </body>
    `,
  });

  const failed = result.rejected.concat(result.pending).filter(Boolean);
  if (failed.length) {
    throw new Error(`Email(s) (${failed.join(", ")}) could not be sent`);
  }
}
