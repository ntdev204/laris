//! The global home and the project folder rules (T155, SR-C3).

mod common;

use common::{env, temp_dir};
use laris_config::home::{
    CREDENTIALS_FILE, HOME_DIRS, Home, HomeError, PROJECT_ENTRIES, ProjectFolder, locate,
};
use std::fs;

#[test]
fn laris_home_wins_over_the_user_home_and_must_be_absolute() {
    let both = env(&[("HOME", "/users/ada"), ("LARIS_HOME", "/data/laris")]);
    assert_eq!(locate(&both).unwrap(), std::path::Path::new("/data/laris"));
    let user = env(&[("HOME", "/users/ada")]);
    assert_eq!(
        locate(&user).unwrap(),
        std::path::Path::new("/users/ada/.laris")
    );
    let windows = env(&[("USERPROFILE", "/users/ada")]);
    assert!(locate(&windows).unwrap().ends_with(".laris"));
    assert!(matches!(
        locate(&env(&[("LARIS_HOME", "relative/dir")])),
        Err(HomeError::NotAbsolute(_))
    ));
    assert!(matches!(locate(&env(&[])), Err(HomeError::NoHome)));
    assert!(matches!(
        locate(&env(&[("HOME", "  ")])),
        Err(HomeError::NoHome)
    ));
}

#[test]
fn an_empty_home_gets_the_whole_layout() {
    let base = temp_dir("fresh-home");
    let home = Home::new(base.join(".laris"));
    let created = home.ensure().unwrap();
    for name in HOME_DIRS {
        assert!(home.root().join(name).is_dir(), "{name}");
    }
    assert_eq!(fs::read_to_string(home.settings_path()).unwrap(), "{}\n");
    assert!(!home.credentials_path().exists(), "no key until login");
    assert_eq!(created.folders.len(), 1 + HOME_DIRS.len());
    assert_eq!(created.files, vec![home.settings_path()]);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = fs::metadata(home.root()).unwrap().permissions().mode();
        assert_eq!(mode & 0o077, 0, "the home is private to the user");
    }
    // The empty settings file is a valid layer.
    let settings = laris_config::load(&laris_config::LoadOptions {
        settings_path: Some(&home.settings_path()),
        packaged: &laris_config::packaged::Packaged::default(),
        env: &[],
    })
    .unwrap();
    assert_eq!(settings, laris_config::Settings::default());
    fs::remove_dir_all(base).ok();
}

#[test]
fn ensure_twice_changes_nothing() {
    let base = temp_dir("twice");
    let home = Home::new(base.join(".laris"));
    home.ensure().unwrap();
    fs::write(home.settings_path(), "{\"ui\": {\"theme\": \"dark\"}}\n").unwrap();
    let again = home.ensure().unwrap();
    assert!(again.is_empty());
    assert_eq!(
        fs::read_to_string(home.settings_path()).unwrap(),
        "{\"ui\": {\"theme\": \"dark\"}}\n",
        "an existing settings file is not touched"
    );
    fs::remove_dir_all(base).ok();
}

#[test]
fn an_existing_home_with_foreign_files_is_left_exactly_as_it_was() {
    let base = temp_dir("foreign-files");
    let root = base.join(".laris");
    fs::create_dir_all(root.join("cache/data")).unwrap();
    fs::create_dir_all(root.join("projects/other-1234")).unwrap();
    fs::write(root.join("notes.yaml"), "model: other\n").unwrap();
    fs::write(root.join("cache/data/state.bin"), [1u8, 2, 3]).unwrap();
    fs::write(
        root.join("projects/other-1234/state.json"),
        "{\"other\": 1}",
    )
    .unwrap();
    fs::write(root.join("settings.json"), "{\"model\": \"other\"}\n").unwrap();
    fs::write(root.join(CREDENTIALS_FILE), "{\"apiKey\": \"other\"}").unwrap();

    let snapshot = |dir: &std::path::Path| {
        let mut out = Vec::new();
        let mut stack = vec![dir.to_path_buf()];
        while let Some(d) = stack.pop() {
            for entry in fs::read_dir(&d).unwrap().flatten() {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else {
                    out.push((path.clone(), fs::read(&path).unwrap()));
                }
            }
        }
        out.sort();
        out
    };
    let before = snapshot(&root);
    let created = Home::new(&root).ensure().unwrap();
    assert_eq!(snapshot(&root), before, "no existing file changed or moved");
    assert!(created.files.is_empty());
    assert!(root.join("cache/data").is_dir(), "nothing was deleted");
    assert!(
        root.join("commands").is_dir(),
        "only what was missing was added"
    );
    fs::remove_dir_all(base).ok();
}

#[test]
fn a_file_where_a_folder_belongs_is_reported_not_replaced() {
    let base = temp_dir("blocked");
    let root = base.join(".laris");
    fs::create_dir_all(&root).unwrap();
    fs::write(root.join("skills"), "a file").unwrap();
    let error = Home::new(&root).ensure().unwrap_err();
    assert!(matches!(error, HomeError::NotAFolder(_)));
    assert_eq!(fs::read_to_string(root.join("skills")).unwrap(), "a file");
    fs::remove_dir_all(base).ok();
}

#[test]
fn a_project_folder_holds_only_its_four_entries() {
    let base = temp_dir("project-entries");
    let project = ProjectFolder::new(&base);
    assert_eq!(
        PROJECT_ENTRIES,
        ["LARIS.md", "skills", "commands", "memory"]
    );
    for name in ["skills", "commands", "memory"] {
        let path = project.create_dir(name).unwrap();
        assert!(path.is_dir());
    }
    for refused in [
        "settings.json",
        "credentials.json",
        "hooks",
        "LARIS.md",
        "..",
    ] {
        assert!(
            matches!(
                project.create_dir(refused),
                Err(HomeError::NotAProjectEntry(_))
            ),
            "{refused}"
        );
        assert!(project.entry(refused).is_none() || refused == "LARIS.md");
    }
    assert!(project.stray().is_empty());
    fs::write(
        project.path().join("settings.json"),
        "{\"permissions\": {}}",
    )
    .unwrap();
    fs::write(project.path().join("LARIS.md"), "# notes").unwrap();
    fs::create_dir(project.path().join("hooks")).unwrap();
    assert_eq!(project.stray(), vec!["hooks", "settings.json"]);
    fs::remove_dir_all(base).ok();
}

#[test]
fn the_project_root_is_found_from_a_subfolder_and_never_the_home_itself() {
    let base = temp_dir("project-root");
    let user = base.join("user");
    let home = Home::new(user.join(".laris"));
    home.ensure().unwrap();
    let repo = user.join("work/paper");
    fs::create_dir_all(repo.join("data/raw")).unwrap();
    fs::create_dir_all(repo.join(".git")).unwrap();
    // A subfolder resolves to the repository.
    assert_eq!(home.project_root(&repo.join("data/raw")), repo);
    // A `.laris` folder marks a project too, and the nearest one wins.
    let inner = repo.join("data");
    fs::create_dir_all(inner.join(".laris/memory")).unwrap();
    assert_eq!(home.project_root(&inner.join("raw")), inner);
    // The user's home directory holds the global `.laris`; that is not a project.
    let plain = user.join("notes");
    fs::create_dir_all(&plain).unwrap();
    assert_eq!(home.project_root(&plain), plain);
    assert_eq!(home.project_root(&user), user);
    fs::remove_dir_all(base).ok();
}
