# cli-auth-consolidation — Input

Multiple CLI commands bypass the daemon API entirely and have no authentication. All telec roadmap subcommands (list, add, remove, move, deps, freeze, unfreeze, deliver), telec todo demo/validate/verify-artifacts/mark-ready/remove/split, telec docs, telec events list, telec signals status, telec history search/show operate directly on the filesystem with no auth.

Two fixes needed:
1. Deny-by-default on the API: if a command is not in the clearance registry, return 403 instead of allowing it. Currently unregistered commands pass through.
2. Route all CLI commands through the API so auth is enforced. The telec roadmap namespace is the worst — every command writes roadmap.yaml and state.yaml directly. Either route through API or kill the namespace and fold into telec todo.

Additional: telec history search help text should document that terms are AND-joined (FTS MATCH). Also history commands need session ownership scoping — callers should only see sessions they own or have role-based access to.
