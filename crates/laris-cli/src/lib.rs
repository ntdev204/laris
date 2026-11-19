//! The `laris` command line. T138 added `laris learn` (SR-H11); T155 adds the global home, the settings the client
//! starts with, and login (SR-C3, SR-C4). The other commands follow with the client.

pub mod account;
pub mod credentials;
pub mod headless;
pub mod learn;
pub mod login;
pub mod replay;
pub mod start;
