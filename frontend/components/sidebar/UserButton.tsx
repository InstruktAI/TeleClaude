"use client";

import { LogOut, Settings, User } from "lucide-react";
import { useSession, signOut } from "next-auth/react";
import { useAgentTheming } from "@/hooks/useAgentTheming";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";

export function UserButton() {
  const { data: session } = useSession();
  const { isThemed } = useAgentTheming();

  if (!session?.user) {
    return null;
  }

  const { name, email, role } = session.user;
  const initials = name
    ? name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "?";

  // Use the new user color tokens when themed, fallback to generic when peaceful
  const avatarStyle = isThemed
    ? { backgroundColor: "var(--tc-user-bubble-bg)", color: "var(--tc-user-bubble-text)" }
    : { backgroundColor: "var(--tc-bg-elevated)", color: "var(--tc-text-primary)" };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex w-full items-center gap-3 rounded-lg p-2 text-left hover:bg-sidebar-accent hover:text-sidebar-accent-foreground outline-none transition-colors"
          aria-label="User menu"
        >
          <Avatar className="h-8 w-8 rounded-md" style={{ backgroundColor: avatarStyle.backgroundColor }}>
            <AvatarFallback 
              className="rounded-md bg-transparent text-xs font-medium"
              style={{ color: avatarStyle.color }}
            >
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-1 flex-col overflow-hidden text-sm">
            <span className="truncate font-semibold">{name}</span>
            <span className="truncate text-xs text-muted-foreground">
              {role || "member"}
            </span>
          </div>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        className="w-56 rounded-xl"
        side="right"
        align="end"
        sideOffset={4}
      >
        <DropdownMenuLabel className="p-0 font-normal">
          <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
            <Avatar className="h-8 w-8 rounded-md" style={{ backgroundColor: avatarStyle.backgroundColor }}>
              <AvatarFallback 
                className="rounded-md bg-transparent text-xs font-medium"
                style={{ color: avatarStyle.color }}
              >
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-semibold">{name}</span>
              <span className="truncate text-xs text-muted-foreground">
                {email}
              </span>
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem className="cursor-pointer">
            <Settings className="mr-2 h-4 w-4" />
            <span>Preferences</span>
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="cursor-pointer text-destructive focus:text-destructive"
          onClick={() => signOut()}
        >
          <LogOut className="mr-2 h-4 w-4" />
          <span>Log out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
