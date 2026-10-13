#!/bin/bash
# Run the installer's release-selection stage the way a maintenance run does: from the installed
# checkout, with the run's serialization already held (TELECLAUDE_MAINTENANCE_DRAIN_HELD).
set -euo pipefail
# shellcheck source=/dev/null
source "$PWD/bin/install.sh" > /dev/null 2>&1
select_installed_release
