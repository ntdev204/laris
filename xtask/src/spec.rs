//! Ledger check: `.claude/spec/spec.md`, `plan/*.md` and `task/*.md` must agree.
//!
//! Rules: requirement ids are unique and each names exactly one known owner; task ids are
//! unique across task files; every task cites known requirements and earlier tasks; every
//! requirement is covered by a task; each plan file lists, phase by phase, exactly the tasks
//! of its task file; statuses are valid; a `done` or `blocked` task has a note; a `done` task
//! has only `done` dependencies; the spec progress index names every phase span.

use regex::Regex;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::process::ExitCode;

const STATUSES: [&str; 4] = ["pending", "in_progress", "done", "blocked"];
const OWNERS: [&str; 8] = [
    "governance",
    "model",
    "protocol",
    "shared",
    "harness",
    "server",
    "client",
    "brain",
];

#[derive(Default, Clone)]
struct Task {
    reqs: Vec<String>,
    deps: Vec<String>,
    status: String,
    note: bool,
}

type Phases = BTreeMap<String, Vec<String>>;

fn requirement_problems(spec: &str) -> (Vec<String>, Vec<String>) {
    let heading = Regex::new(r"^### (SR-[A-Z]\d+) — ").expect("static regex");
    let owner = Regex::new(r"^Owner: *(\S*)\s*$").expect("static regex");
    let mut blocks: Vec<Vec<&str>> = Vec::new();
    for line in spec.lines() {
        if line.starts_with("### ") || blocks.is_empty() {
            blocks.push(Vec::new());
        }
        if let Some(block) = blocks.last_mut() {
            block.push(line);
        }
    }
    let (mut problems, mut reqs) = (Vec::new(), Vec::<String>::new());
    for block in blocks {
        let Some(caps) = heading.captures(block[0]) else {
            continue;
        };
        let req = caps[1].to_string();
        if reqs.contains(&req) {
            problems.push(format!("{req}: duplicate requirement id"));
        }
        reqs.push(req.clone());
        let owners: Vec<String> = block
            .iter()
            .filter_map(|l| owner.captures(l).map(|c| c[1].to_string()))
            .collect();
        match owners.as_slice() {
            [one] if OWNERS.contains(&one.as_str()) => {}
            [one] => problems.push(format!("{req}: unknown owner '{one}'")),
            other => problems.push(format!(
                "{req}: needs exactly one Owner line, found {}",
                other.len()
            )),
        }
    }
    (reqs, problems)
}

fn find_all(re: &Regex, text: &str) -> Vec<String> {
    re.find_iter(text).map(|m| m.as_str().to_string()).collect()
}

fn parse_tasks(text: &str) -> (Vec<(String, Task)>, Phases) {
    let phase_re = Regex::new(r"^## (Phase \d+)").expect("static regex");
    let task_re = Regex::new(r"^### (T\d+) — ").expect("static regex");
    let req_re = Regex::new(r"SR-[A-Z]\d+").expect("static regex");
    let dep_re = Regex::new(r"T\d+").expect("static regex");
    let mut tasks: Vec<(String, Task)> = Vec::new();
    let mut phases = Phases::new();
    let mut phase = String::new();
    let mut open = false;
    for line in text.lines() {
        if let Some(c) = phase_re.captures(line) {
            phase = c[1].to_string();
            open = false;
            phases.entry(phase.clone()).or_default();
        } else if let Some(c) = task_re.captures(line) {
            tasks.push((c[1].to_string(), Task::default()));
            phases
                .entry(phase.clone())
                .or_default()
                .push(c[1].to_string());
            open = true;
        } else if open {
            let Some((_, entry)) = tasks.last_mut() else {
                continue;
            };
            if line.starts_with("- Requirements:") {
                entry.reqs = find_all(&req_re, line);
            } else if line.starts_with("- Depends:") {
                entry.deps = find_all(&dep_re, line);
            } else if let Some(rest) = line.strip_prefix("- Status:") {
                entry.status = rest.trim().to_string();
            } else if line.starts_with("- Note:") {
                entry.note = true;
            }
        }
    }
    (tasks, phases)
}

fn parse_plan(text: &str) -> Phases {
    let phase_re = Regex::new(r"^### (Phase \d+)").expect("static regex");
    let dep_re = Regex::new(r"T\d+").expect("static regex");
    let mut phases = Phases::new();
    let mut phase = String::new();
    for line in text.lines() {
        if let Some(c) = phase_re.captures(line) {
            phase = c[1].to_string();
        } else if !phase.is_empty() && line.starts_with("Tasks:") {
            phases.insert(phase.clone(), find_all(&dep_re, line));
        }
    }
    phases
}

fn number(id: &str) -> u32 {
    id[1..].parse().unwrap_or(0)
}

fn validate(
    spec: &str,
    plans: &BTreeMap<String, String>,
    task_files: &BTreeMap<String, String>,
) -> Vec<String> {
    let (reqs, mut problems) = requirement_problems(spec);
    let plan_names: Vec<_> = plans.keys().collect();
    let task_names: Vec<_> = task_files.keys().collect();
    if plan_names != task_names {
        problems.push(format!(
            "plan files {plan_names:?} and task files {task_names:?} differ"
        ));
    }
    let mut order: Vec<String> = Vec::new();
    let mut tasks: HashMap<String, Task> = HashMap::new();
    let mut all_phases = Phases::new();
    for (name, text) in task_files {
        let (parsed, phases) = parse_tasks(text);
        for (id, entry) in parsed {
            if tasks.contains_key(&id) {
                problems.push(format!("{id}: duplicate task id ({name})"));
            } else {
                order.push(id.clone());
            }
            tasks.insert(id, entry);
        }
        for (phase, items) in &phases {
            if all_phases.contains_key(phase) && !items.is_empty() {
                problems.push(format!("{phase}: appears in more than one task file"));
            }
            all_phases.insert(phase.clone(), items.clone());
        }
        let plan_phases = parse_plan(plans.get(name).map_or("", String::as_str));
        let non_empty: Phases = phases.into_iter().filter(|(_, v)| !v.is_empty()).collect();
        if plan_phases != non_empty {
            problems.push(format!(
                "plan/{name} phases do not list the same tasks as task/{name}"
            ));
        }
    }
    if tasks.is_empty() {
        problems.push("no tasks found".to_string());
    }
    let mut covered = HashSet::new();
    for id in &order {
        let entry = &tasks[id];
        if entry.reqs.is_empty() {
            problems.push(format!("{id}: no requirements cited"));
        }
        for req in &entry.reqs {
            if !reqs.contains(req) {
                problems.push(format!("{id}: unknown requirement {req}"));
            }
            covered.insert(req.clone());
        }
        for dep in &entry.deps {
            match tasks.get(dep) {
                None => problems.push(format!("{id}: unknown dependency {dep}")),
                Some(_) if number(dep) >= number(id) => {
                    problems.push(format!("{id}: dependency {dep} must come earlier"));
                }
                Some(d) if entry.status == "done" && d.status != "done" => {
                    problems.push(format!("{id}: done but dependency {dep} is not done"));
                }
                Some(_) => {}
            }
        }
        if !STATUSES.contains(&entry.status.as_str()) {
            problems.push(format!("{id}: invalid status '{}'", entry.status));
        }
        if (entry.status == "done" || entry.status == "blocked") && !entry.note {
            problems.push(format!("{id}: {} needs a note", entry.status));
        }
    }
    for req in &reqs {
        if !covered.contains(req) {
            problems.push(format!("{req}: not covered by any task"));
        }
    }
    match spec.find("## 10. Task progress index") {
        None => problems.push("spec.md has no section 10 task progress index".to_string()),
        Some(at) => {
            let index = &spec[at..];
            for (phase, items) in &all_phases {
                if let (Some(first), Some(last)) = (items.first(), items.last())
                    && !index.contains(&format!("{phase}: {first}-{last}"))
                {
                    problems.push(format!(
                        "spec.md progress index misses {phase}: {first}-{last}"
                    ));
                }
            }
        }
    }
    problems
}

fn read_dir(dir: &Path) -> BTreeMap<String, String> {
    let mut files = BTreeMap::new();
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|e| e == "md")
                && let (Some(name), Ok(text)) = (path.file_name(), fs::read_to_string(&path))
            {
                files.insert(name.to_string_lossy().into_owned(), text);
            }
        }
    }
    files
}

/// Run the ledger check under `root`; exit code 0 when ledger files agree.
pub fn run(root: &Path) -> ExitCode {
    let base = root.join(".claude").join("spec");
    let Ok(spec) = fs::read_to_string(base.join("spec.md")) else {
        println!("[FAIL] cannot read {}", base.join("spec.md").display());
        return ExitCode::FAILURE;
    };
    let task_files = read_dir(&base.join("task"));
    let problems = validate(&spec, &read_dir(&base.join("plan")), &task_files);
    for problem in &problems {
        println!("[FAIL] {problem}");
    }
    if !problems.is_empty() {
        return ExitCode::FAILURE;
    }
    let all: Vec<Task> = task_files
        .values()
        .flat_map(|t| parse_tasks(t).0.into_iter().map(|(_, e)| e))
        .collect();
    let done = all.iter().filter(|t| t.status == "done").count();
    println!(
        "[PASS] spec.md, {} plan and task files agree ({} tasks, {done} done).",
        task_files.len(),
        all.len()
    );
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::*;

    const SPEC: &str =
        "### SR-X1 — one\nOwner: model\n\n## 10. Task progress index\nPhase 1: T1-T2\n";
    const TASKS: &str = "## Phase 1\n### T1 — a\n- Requirements: SR-X1\n- Depends: \n- Status: done\n- Note: ok\n### T2 — b\n- Requirements: SR-X1\n- Depends: T1\n- Status: pending\n";
    const PLAN: &str = "### Phase 1\nTasks: T1, T2\n";

    fn check(spec: &str, tasks: &str, plan: &str) -> Vec<String> {
        let one = |t: &str| BTreeMap::from([("1.md".to_string(), t.to_string())]);
        validate(spec, &one(plan), &one(tasks))
    }

    #[test]
    fn consistent_ledger_passes() {
        assert!(check(SPEC, TASKS, PLAN).is_empty());
    }

    #[test]
    fn unknown_owner_fails() {
        let spec = SPEC.replace("Owner: model", "Owner: nobody");
        assert!(!check(&spec, TASKS, PLAN).is_empty());
    }

    #[test]
    fn done_without_note_fails() {
        let tasks = TASKS.replace("- Note: ok\n", "");
        assert!(
            check(SPEC, &tasks, PLAN)
                .iter()
                .any(|p| p.contains("needs a note"))
        );
    }

    #[test]
    fn plan_mismatch_fails() {
        assert!(!check(SPEC, TASKS, "### Phase 1\nTasks: T1\n").is_empty());
    }
}
