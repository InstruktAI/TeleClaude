"use client";

import { MyRuntimeProvider } from "./MyRuntimeProvider";
import { ThreadView } from "./ThreadView";

export default function Chat() {
  return (
    <MyRuntimeProvider>
      <ThreadView />
    </MyRuntimeProvider>
  );
}
