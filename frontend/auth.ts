import NextAuth from "next-auth";
import Nodemailer from "next-auth/providers/nodemailer";
import { DrizzleAdapter } from "@auth/drizzle-adapter";
import { db } from "@/lib/db";
import {
  users,
  accounts,
  sessions,
  verificationTokens,
} from "@/lib/db/schema";
import { sendVerificationRequest } from "@/lib/identity/email";
import { findPersonByEmail } from "@/lib/identity/people";

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: DrizzleAdapter(db, {
    usersTable: users,
    accountsTable: accounts,
    sessionsTable: sessions,
    verificationTokensTable: verificationTokens,
  }),

  providers: [
    Nodemailer({
      server: {
        host: process.env.SMTP_HOST,
        port: Number(process.env.SMTP_PORT ?? 587),
        auth: {
          user: process.env.SMTP_USER,
          pass: process.env.SMTP_PASS,
        },
      },
      from: process.env.EMAIL_FROM ?? "TeleClaude <noreply@teleclaude.dev>",
      maxAge: 3 * 60,
      generateVerificationToken() {
        return Math.floor(100000 + Math.random() * 900000).toString();
      },
      sendVerificationRequest,
    }),
  ],

  pages: {
    signIn: "/login",
    verifyRequest: "/login?verify=1",
    error: "/login?error=1",
  },

  session: {
    strategy: "database",
    maxAge: 30 * 24 * 60 * 60,
  },

  callbacks: {
    async signIn({ user }) {
      if (!user.email) return false;
      const person = findPersonByEmail(user.email);
      if (!person) return false;
      return true;
    },

    async session({ session, user }) {
      session.user.id = user.id;
      if (user.email) {
        const person = findPersonByEmail(user.email);
        if (person) {
          session.user.name = person.name;
          (session as SessionWithRole).user.role = person.role;
        }
      }
      return session;
    },
  },
});

interface SessionWithRole {
  user: {
    id: string;
    name?: string | null;
    email?: string | null;
    image?: string | null;
    role?: string;
  };
}
