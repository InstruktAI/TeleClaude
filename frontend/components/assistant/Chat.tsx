"use client";

import { MyRuntimeProvider } from "./MyRuntimeProvider";
import { ThreadView } from "./ThreadView";

interface Props {
  sessionId: string;
}

export default function Chat({ sessionId }: Props) {
  return (
    <MyRuntimeProvider sessionId={sessionId}>
      <ThreadView />
    </MyRuntimeProvider>
  );
}
