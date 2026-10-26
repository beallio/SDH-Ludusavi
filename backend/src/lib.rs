//! Native SDH-Ludusavi backend.
mod http;
pub mod launch_gate;
pub mod lifecycle;
pub mod operations;
pub mod singleton;
pub mod syncthing;
pub mod watchdog;

pub mod persistence;
#[cfg(test)]
mod phase4_tests;
pub mod service;
pub mod status_theme;
pub mod updater;
