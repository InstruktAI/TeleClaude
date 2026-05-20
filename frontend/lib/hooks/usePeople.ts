'use client';

import { useQuery } from '@tanstack/react-query';
import type { PersonInfo } from '@/lib/api/types';

async function fetchPeople(): Promise<PersonInfo[]> {
  const res = await fetch('/api/people');
  if (!res.ok) throw new Error(`Failed to fetch people: ${res.status}`);
  return res.json();
}

export function usePeople() {
  return useQuery({
    queryKey: ['people'],
    queryFn: fetchPeople,
  });
}
