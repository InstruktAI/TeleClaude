'use client';

import type { TextMessagePartProps } from '@assistant-ui/react';

export function PlainTextContent(props: TextMessagePartProps) {
  return <div className="whitespace-pre-wrap break-words text-sm">{props.text}</div>;
}
