//! Incremental builds, file handling and link resolution on a vault that the test writes itself.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};

use laris_vault::index::Resolution;
use laris_vault::{Link, VaultIndex};

/// A folder under the system temp directory, removed on drop.
struct Temp(PathBuf);

impl Temp {
    fn new(name: &str) -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-vault-{name}-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        Temp(dir)
    }

    fn write(&self, rel: &str, text: &str) {
        let path = self.0.join(rel);
        fs::create_dir_all(path.parent().expect("parent")).expect("dirs");
        fs::write(path, text).expect("write");
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn copy_dir(from: &Path, to: &Path) {
    fs::create_dir_all(to).expect("dir");
    for entry in fs::read_dir(from).expect("read") {
        let entry = entry.expect("entry");
        let target = to.join(entry.file_name());
        if entry.file_type().expect("type").is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).expect("copy");
        }
    }
}

#[test]
fn rebuild_reads_only_what_changed_and_equals_a_fresh_build() {
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/golden/vault/fixture");
    let temp = Temp::new("incremental");
    copy_dir(&fixture, &temp.0);
    let first = VaultIndex::build(&temp.0, None).expect("build");
    let total = first.notes.len();
    assert_eq!(first.stats.parsed.len(), total);

    // change one note (its size changes), add one, delete one
    temp.write(
        "Notes/Beta.md",
        "---\ntype: concept\n---\n\nNow it links to [[Lonely]] and [[Brand New]].\n",
    );
    temp.write("Brand New.md", "new note [[Beta]]\n");
    fs::remove_file(temp.0.join("Lonely.md")).expect("remove");
    let second = VaultIndex::build(&temp.0, Some(&first)).expect("build");
    let mut parsed = second.stats.parsed.clone();
    parsed.sort();
    assert_eq!(parsed, ["Brand New.md", "Notes/Beta.md"]);
    assert_eq!(second.stats.reused.len(), total - 2);
    assert!(!second.notes.contains_key("Lonely.md"));
    assert_eq!(
        second
            .unresolved
            .iter()
            .filter(|(p, t)| p == "Notes/Beta.md" && t == "Lonely")
            .count(),
        1
    );

    let fresh = VaultIndex::build(&temp.0, None).expect("build");
    assert_eq!(second.export_string(), fresh.export_string());
    assert!(
        second
            .backlinks("Notes/Beta.md")
            .contains(&"Brand New.md".to_string())
    );
}

#[test]
fn line_endings_are_normalised_before_hashing_as_in_generation_1() {
    let temp = Temp::new("crlf");
    temp.write(
        "Win.md",
        "---\r\ntype: concept\r\n---\r\nBody [[Other]]\r\n",
    );
    temp.write("Unix.md", "---\ntype: concept\n---\nBody [[Other]]\n");
    let index = VaultIndex::build(&temp.0, None).expect("build");
    assert_eq!(index.notes["Win.md"].sha256, index.notes["Unix.md"].sha256);
    assert_eq!(index.notes["Win.md"].props.len(), 1);
}

#[test]
fn invalid_utf8_is_replaced_not_fatal() {
    let temp = Temp::new("utf8");
    fs::write(temp.0.join("Bad.md"), b"caf\xe9 [[Other]]\n").expect("write");
    let index = VaultIndex::build(&temp.0, None).expect("build");
    assert!(index.notes["Bad.md"].body.contains('\u{fffd}'));
}

#[cfg(unix)]
#[test]
fn symlinks_inside_are_read_and_outside_or_folder_links_are_not() {
    use std::os::unix::fs::symlink;
    let outside = Temp::new("outside");
    outside.write("Secret.md", "secret [[Inside]]\n");
    outside.write("Folder/Deep.md", "deep\n");
    let temp = Temp::new("links");
    temp.write("Inside.md", "inside\n");
    symlink(temp.0.join("Inside.md"), temp.0.join("Alias.md")).expect("link");
    symlink(outside.0.join("Secret.md"), temp.0.join("Leak.md")).expect("link");
    symlink(outside.0.join("Folder"), temp.0.join("Linked")).expect("link");
    symlink(temp.0.join("missing.md"), temp.0.join("Broken.md")).expect("link");
    let index = VaultIndex::build(&temp.0, None).expect("build");
    assert_eq!(
        index.notes.keys().collect::<Vec<_>>(),
        ["Alias.md", "Inside.md"]
    );
}

#[test]
fn a_missing_root_is_an_error() {
    let temp = Temp::new("missing");
    assert!(VaultIndex::build(&temp.0.join("nope"), None).is_err());
    temp.write("file.md", "x");
    assert!(VaultIndex::build(&temp.0.join("file.md"), None).is_err());
}

#[test]
fn resolution_follows_the_shortest_path_rule() {
    let temp = Temp::new("resolve");
    temp.write("Notes/Alpha.md", "a\n");
    temp.write("Notes/Twin.md", "t1\n");
    temp.write("Alt/Twin.md", "t2\n");
    temp.write("Deep/Er/Same.md", "s\n");
    let index = VaultIndex::build(&temp.0, None).expect("build");
    let at = |name: &str| index.resolve(&Link::to(name), "Notes/Alpha.md");
    assert_eq!(at("alpha"), (Some("Notes/Alpha.md".into()), Resolution::Ok));
    assert_eq!(
        at("ALPHA.MD"),
        (Some("Notes/Alpha.md".into()), Resolution::Ok)
    );
    assert_eq!(
        at("Notes/Alpha"),
        (Some("Notes/Alpha.md".into()), Resolution::Ok)
    );
    assert_eq!(
        at("Er/Same"),
        (Some("Deep/Er/Same.md".into()), Resolution::Ok)
    );
    assert_eq!(at("Twin"), (None, Resolution::Ambiguous));
    assert_eq!(at("Alt/Twin"), (Some("Alt/Twin.md".into()), Resolution::Ok));
    assert_eq!(at("Gone"), (None, Resolution::Missing));
    assert_eq!(
        at(""),
        (Some("Notes/Alpha.md".into()), Resolution::SelfLink)
    );
    assert_eq!(index.find("twin").map(|n| n.path.as_str()), None);
    assert_eq!(
        index.find("same").map(|n| n.path.as_str()),
        Some("Deep/Er/Same.md")
    );
}

#[test]
fn properties_link_by_name_and_by_property() {
    let temp = Temp::new("props");
    temp.write(
        "Hub.md",
        "---\nchildren:\n- '[[Leaf One]]'\n- '[[Leaf Two]]'\n- '[[Ghost]]'\ntype: hub\n---\n",
    );
    temp.write(
        "Leaf One.md",
        "---\nparent: '[[Hub]]'\ntype: concept\n---\n",
    );
    temp.write("Leaf Two.md", "---\ntype: concept\n---\n");
    let index = VaultIndex::build(&temp.0, None).expect("build");
    assert_eq!(
        index.targets("Hub.md", "children"),
        ["Leaf One.md", "Leaf Two.md"]
    );
    assert_eq!(
        index.outgoing("Hub.md"),
        [
            ("Leaf One.md".to_string(), "children".to_string()),
            ("Leaf Two.md".to_string(), "children".to_string())
        ]
    );
    assert_eq!(index.backlinks("Hub.md"), ["Leaf One.md"]);
    assert_eq!(
        index.unresolved,
        [("Hub.md".to_string(), "Ghost".to_string())]
    );
    assert_eq!(index.by_prop("type", "concept").len(), 2);
    assert!(index.unlinked().is_empty());
    assert!(index.orphans().is_empty());
}
