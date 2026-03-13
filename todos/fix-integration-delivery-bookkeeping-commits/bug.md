# Bug: Integration delivery bookkeeping commits on repo root main diverge from origin/main. The delivery squash commit is pushed from trees/_integration/ worktree, but bookkeeping (roadmap deliver, todo cleanup) runs on repo root main. This creates a divergence requiring manual merge every time. Bookkeeping should either run in the integration worktree before push, or repo root should pull after the worktree push.

## Symptom

Integration delivery bookkeeping commits on repo root main diverge from origin/main. The delivery squash commit is pushed from trees/_integration/ worktree, but bookkeeping (roadmap deliver, todo cleanup) runs on repo root main. This creates a divergence requiring manual merge every time. Bookkeeping should either run in the integration worktree before push, or repo root should pull after the worktree push.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
