use std::time::Duration;

use chrono::{DateTime, Utc};
use reconciliation::{
    FleetCapabilityEntry, FleetCapabilityMap, FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
};

fn ts(raw: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(raw)
        .expect("timestamp parses")
        .with_timezone(&Utc)
}

#[test]
fn safe_to_require_false_until_all_live_nodes_carry() {
    let now = ts("2026-06-12T00:00:00Z");
    let alpha = FleetCapabilityEntry::new(
        "alpha-node",
        Some("1.3.0".to_string()),
        Some("alpha".to_string()),
        [FLEET_CROSS_VERSION_INTEROP_FEATURE_ID.to_string()],
        now,
    )
    .expect("alpha entry");
    let stable = FleetCapabilityEntry::new(
        "stable-node",
        Some("1.2.5".to_string()),
        Some("stable".to_string()),
        Vec::<String>::new(),
        now,
    )
    .expect("stable entry");

    let partial =
        FleetCapabilityMap::materialize([alpha.clone(), stable], now, Duration::from_secs(60))
            .expect("map");
    let complete =
        FleetCapabilityMap::materialize([alpha], now, Duration::from_secs(60)).expect("map");

    assert!(!partial.safe_to_require(FLEET_CROSS_VERSION_INTEROP_FEATURE_ID));
    assert!(complete.safe_to_require(FLEET_CROSS_VERSION_INTEROP_FEATURE_ID));
    assert!(complete.safe_to_contract(FLEET_CROSS_VERSION_INTEROP_FEATURE_ID));
}

#[test]
fn aged_out_entry_excluded() {
    let now = ts("2026-06-12T00:01:01Z");
    let stale = FleetCapabilityEntry::new(
        "stale-node",
        Some("1.1.0".to_string()),
        Some("stable".to_string()),
        Vec::<String>::new(),
        ts("2026-06-12T00:00:00Z"),
    )
    .expect("stale entry");
    let live = FleetCapabilityEntry::new(
        "live-node",
        Some("1.2.5".to_string()),
        Some("stable".to_string()),
        [FLEET_CROSS_VERSION_INTEROP_FEATURE_ID.to_string()],
        now,
    )
    .expect("live entry");

    let map =
        FleetCapabilityMap::materialize([stale, live], now, Duration::from_secs(60)).expect("map");

    assert_eq!(map.entries.len(), 1);
    assert_eq!(map.entries[0].computer, "live-node");
    assert!(map.safe_to_require(FLEET_CROSS_VERSION_INTEROP_FEATURE_ID));
}
