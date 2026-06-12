use config::{DeploymentConfig, ProjectConfig};
use reconciliation::{select_target, ReleaseSignal};

fn deployment(yaml: &str) -> DeploymentConfig {
    serde_yaml::from_str::<ProjectConfig>(yaml)
        .expect("project config parses")
        .deployment
}

#[test]
fn alpha_converges_on_newest_mainline() {
    let deployment = deployment(
        r#"
deployment:
  channel: alpha
"#,
    );
    let signal = ReleaseSignal::mainline("main-sha-1", "delivery-1").expect("signal");

    let target = select_target(&signal, &deployment)
        .expect("policy evaluates")
        .expect("target selected");

    assert_eq!(target.as_str(), "main-sha-1");
}

#[test]
fn beta_converges_on_release() {
    let deployment = deployment(
        r#"
deployment:
  channel: beta
"#,
    );
    let signal = ReleaseSignal::published_release("v1.2.5", "delivery-1").expect("signal");

    let target = select_target(&signal, &deployment)
        .expect("policy evaluates")
        .expect("target selected");

    assert_eq!(target.as_str(), "1.2.5");
}

#[test]
fn beta_ignores_unpublished_mainline() {
    let deployment = deployment(
        r#"
deployment:
  channel: beta
"#,
    );
    let signal = ReleaseSignal::mainline("main-sha-1", "delivery-1").expect("signal");

    let target = select_target(&signal, &deployment).expect("policy evaluates");

    assert!(target.is_none());
}

#[test]
fn stable_converges_within_pin() {
    let deployment = deployment(
        r#"
deployment:
  channel: stable
  pinned_minor: '1.2'
"#,
    );
    let signal = ReleaseSignal::published_release("1.2.5", "delivery-1").expect("signal");

    let target = select_target(&signal, &deployment)
        .expect("policy evaluates")
        .expect("target selected");

    assert_eq!(target.as_str(), "1.2.5");
}

#[test]
fn stable_rejects_out_of_pin() {
    let deployment = deployment(
        r#"
deployment:
  channel: stable
  pinned_minor: '1.2'
"#,
    );
    let signal = ReleaseSignal::published_release("1.3.0", "delivery-1").expect("signal");

    let target = select_target(&signal, &deployment).expect("policy evaluates");

    assert!(target.is_none());
}
