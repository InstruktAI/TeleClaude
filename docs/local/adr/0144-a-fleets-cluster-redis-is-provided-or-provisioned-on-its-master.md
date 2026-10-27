---
visibility: public
number: 144
date: 2026-10-27
description: A lone computer's cluster Redis is its own local Redis; a fleet's is an endpoint its operator provides or a TLS Redis TeleClaude provisions on the master; a fresh install asks only what decides that.
---

# A Fleet's Cluster Redis Is Provided or Provisioned on Its Master — ADR

## Context

The platform cannot start without a cluster Redis. Until now its URL was
whatever the operator configured, with a default naming a Redis on the same
computer that the installer started. With every computer running its own local
Redis (ADR-0143), a computer installed on its own needs no second Redis, and a
fresh fleet has no shared Redis for its computers to reach unless someone
provides one.

## Decision

- **A lone computer names its own local Redis as its cluster Redis.** The
  cluster settings carry its socket, user and password, so the computer is a
  fleet of one with nothing in a hidden mode; when both scopes name the same
  Redis, the event platform reads it once. The cluster Redis stays required.
- **A fleet's cluster Redis comes from its master.** Installing the master
  offers to provision one there or to use an endpoint the operator provides. A
  provisioned cluster Redis is a second instance of TeleClaude's own: it listens
  only on TLS with a certificate from a private authority TeleClaude creates,
  requires a cluster ACL user, and the install prints the join details the other
  computers enter: its address, user, password and certificate authority.
  Clients verify the cluster Redis against that authority.
- **A fresh install asks only what decides this**: whether this is the only
  computer, whether it is the master, and, on the master, provision or endpoint;
  a computer that is not the master asks for the join details. The answers go
  into the existing configuration, `computer.is_master` and the cluster
  settings with their secrets in the machine environment. Later installs ask
  nothing, a scripted install passes the same answers as arguments, and the
  install ends by pointing at `telec` for the rest of the configuration.

## Consequences

- A single-computer install works with no Redis of the operator's own.
- Reaching a provisioned cluster Redis from outside its network is the
  operator's: a VPN or a forwarded port.
- Growing a lone computer into a fleet, or moving the master, changes the
  cluster settings on every computer; both stay possible as reconfiguration.
- Connections to a `rediss://` cluster Redis verify its certificate instead of
  accepting any.

## Alternatives Considered

- **No cluster Redis configured means the computer runs alone.** Rejected: a
  computer that loses its cluster settings would silently become an island.
- **Always require an operator-provided endpoint.** Rejected: a single computer
  would need a Redis its operator runs for nothing.
- **Provision the cluster Redis wherever the install runs.** Rejected: the master
  is the always-on computer the fleet already depends on for central
  management, so it is where a shared service stays reachable.
