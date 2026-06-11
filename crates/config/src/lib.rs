//! config — overlay-based configuration service.
//!
//! Owns the runtime config model and the loader that turns three YAML
//! sources (global, project, person) into an effective [`Config`]. The
//! service is stateless — config is authored content, read from disk at
//! startup. There is no Postgres schema.
//!
//! See `docs/project/design/architecture-v2/services.md` (section: config)
//! for the ownership boundary.

pub mod effective;
pub mod errors;
pub mod loaders;
pub mod models;
pub mod service;
pub mod validate;

pub use effective::{effective_config, find_person_entry};
pub use errors::ConfigError;
pub use loaders::{
    load_global, load_person, load_project, ConfigOverlayPaths, GlobalOverlay, PersonOverlay,
    ProjectOverlay,
};
pub use models::{
    ChannelSubscription, Config, DeploymentChannel, DeploymentConfig, GlobalConfig, HooksConfig,
    InboundHook, PersonConfig, PersonEntry, ProjectConfig,
};
pub use service::ConfigService;
pub use validate::{
    validate, validate_global, validate_person_entry, validate_person_overlay, validate_project,
    KNOWN_ROLES,
};
