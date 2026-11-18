//! Windows backend (option A, T134 decision 2): a write-restricted token, ACLs on the writable roots, a job object.
//!
//! Approach after codex's restricted-token path (`codex-rs/windows-sandbox-rs`, Apache-2.0, commit
//! `aa5f492031f7edb75a40973d19eda8efb9512c61`), rewritten small against the LARIS `Policy`; nothing is copied.
//! Modified by LARIS: no elevated users, no firewall, no private desktop, no ConPTY.
//!
//! How it confines: the helper makes a copy of its own token with `WRITE_RESTRICTED` and the restricting SIDs
//! {capability, logon, Everyone}. A write then needs the normal check and the restricting check to pass, and the only
//! restricting SID that the user's own folders grant is the capability SID, which the helper grants on the writable
//! roots (and denies on the protected names) just before it starts the command. The command runs in a job object that
//! kills it when the helper ends.
//!
//! This is the only module of the crate that uses `unsafe` (raw Win32 calls). **Built for `x86_64-pc-windows-msvc`
//! with `cargo check` only; it has never run on Windows.**
#![allow(unsafe_code)]

use crate::winargs::{self, WindowsRestrictions};
use std::ffi::{OsStr, OsString, c_void};
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr::{null, null_mut};
use windows_sys::Win32::Foundation::{
    CloseHandle, ERROR_SUCCESS, GetLastError, HANDLE, INVALID_HANDLE_VALUE, LocalFree,
};
use windows_sys::Win32::Security::Authorization::{
    ConvertSidToStringSidW, ConvertStringSidToSidW, DENY_ACCESS, EXPLICIT_ACCESS_W, GRANT_ACCESS,
    GetNamedSecurityInfoW, SE_FILE_OBJECT, SetEntriesInAclW, SetNamedSecurityInfoW, TRUSTEE_IS_SID,
    TRUSTEE_IS_UNKNOWN, TRUSTEE_W,
};
use windows_sys::Win32::Security::{
    ACL, CreateRestrictedToken, DACL_SECURITY_INFORMATION, DISABLE_MAX_PRIVILEGE,
    GetTokenInformation, SID_AND_ATTRIBUTES, SUB_CONTAINERS_AND_OBJECTS_INHERIT,
    SetTokenInformation, TOKEN_ADJUST_DEFAULT, TOKEN_ADJUST_SESSIONID, TOKEN_ASSIGN_PRIMARY,
    TOKEN_DEFAULT_DACL, TOKEN_DUPLICATE, TOKEN_GROUPS, TOKEN_QUERY, TOKEN_USER, TokenDefaultDacl,
    TokenGroups, TokenUser, WRITE_RESTRICTED,
};
use windows_sys::Win32::Storage::FileSystem::{
    DELETE, FILE_DELETE_CHILD, FILE_GENERIC_EXECUTE, FILE_GENERIC_READ, FILE_GENERIC_WRITE,
};
use windows_sys::Win32::System::Console::{
    GetStdHandle, STD_ERROR_HANDLE, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
    SetInformationJobObject,
};
use windows_sys::Win32::System::Threading::{
    CREATE_SUSPENDED, CreateProcessAsUserW, GetCurrentProcess, GetExitCodeProcess, INFINITE,
    OpenProcessToken, PROCESS_INFORMATION, ResumeThread, STARTF_USESTDHANDLES, STARTUPINFOW,
    WaitForSingleObject,
};

const GENERIC_ALL: u32 = 0x1000_0000;
const SE_GROUP_LOGON_ID: u32 = 0xC000_0000;

/// Owns a Win32 handle.
struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
            // SAFETY: the handle is owned here and closed once.
            unsafe { CloseHandle(self.0) };
        }
    }
}

/// Owns memory from `LocalAlloc` (SIDs and ACLs the system allocated).
struct Local(*mut c_void);
impl Drop for Local {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: allocated by the system with LocalAlloc, freed once.
            unsafe { LocalFree(self.0) };
        }
    }
}

fn last_error(what: &str) -> String {
    // SAFETY: plain call.
    format!("{what} failed (Win32 error {})", unsafe { GetLastError() })
}

fn wide(s: &OsStr) -> Vec<u16> {
    s.encode_wide().chain(std::iter::once(0)).collect()
}

fn sid_from_string(s: &str) -> Result<Local, String> {
    let w = wide(OsStr::new(s));
    let mut sid = null_mut();
    // SAFETY: `w` is NUL terminated; the result is freed by `Local`.
    if unsafe { ConvertStringSidToSidW(w.as_ptr(), &mut sid) } == 0 {
        return Err(last_error("ConvertStringSidToSidW"));
    }
    Ok(Local(sid))
}

fn sid_to_string(sid: *mut c_void) -> Result<String, String> {
    let mut out = null_mut();
    // SAFETY: `sid` is a valid SID; `out` is freed by `Local`.
    if unsafe { ConvertSidToStringSidW(sid, &mut out) } == 0 {
        return Err(last_error("ConvertSidToStringSidW"));
    }
    let owned = Local(out.cast());
    // SAFETY: `out` is a NUL-terminated UTF-16 string.
    let len = (0..).take_while(|&i| unsafe { *out.add(i) } != 0).count();
    let text = String::from_utf16_lossy(unsafe { std::slice::from_raw_parts(out, len) });
    drop(owned);
    Ok(text)
}

/// Reads a variable-size token information block.
fn token_info(token: HANDLE, class: i32) -> Result<Vec<u64>, String> {
    let mut len = 0u32;
    // SAFETY: a size query with a null buffer.
    unsafe { GetTokenInformation(token, class, null_mut(), 0, &mut len) };
    // u64 elements keep the buffer 8-byte aligned for the structures read from it
    let mut buf = vec![0u64; (len as usize).div_ceil(8).max(1)];
    // SAFETY: `buf` holds `len` bytes.
    if unsafe { GetTokenInformation(token, class, buf.as_mut_ptr().cast(), len, &mut len) } == 0 {
        return Err(last_error("GetTokenInformation"));
    }
    Ok(buf)
}

/// An ACL entry for `sid` (`TRUSTEE_W` keeps a pointer to it, so `sid` must outlive the entry).
fn entry(sid: *mut c_void, mode: i32, access: u32, inherit: u32) -> EXPLICIT_ACCESS_W {
    EXPLICIT_ACCESS_W {
        grfAccessPermissions: access,
        grfAccessMode: mode,
        grfInheritance: inherit,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.cast(),
        },
    }
}

/// Adds `entries` to the DACL of `path`, ahead of what is there.
fn add_to_dacl(path: &Path, entries: &[EXPLICIT_ACCESS_W]) -> Result<(), String> {
    let name = wide(path.as_os_str());
    let mut old: *mut ACL = null_mut();
    let mut descriptor = null_mut();
    // SAFETY: `name` is NUL terminated; `descriptor` owns `old` and is freed by `Local`.
    let status = unsafe {
        GetNamedSecurityInfoW(
            name.as_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            null_mut(),
            null_mut(),
            &mut old,
            null_mut(),
            &mut descriptor,
        )
    };
    let _descriptor = Local(descriptor);
    if status != ERROR_SUCCESS {
        return Err(format!(
            "cannot read the ACL of {} (error {status})",
            path.display()
        ));
    }
    let mut new: *mut ACL = null_mut();
    // SAFETY: `entries` and `old` are valid; `new` is freed by `Local`.
    let status = unsafe { SetEntriesInAclW(entries.len() as u32, entries.as_ptr(), old, &mut new) };
    let _new = Local(new.cast());
    if status != ERROR_SUCCESS {
        return Err(format!(
            "cannot build the ACL of {} (error {status})",
            path.display()
        ));
    }
    // SAFETY: `name` is NUL terminated and `new` is a valid ACL.
    let status = unsafe {
        SetNamedSecurityInfoW(
            name.as_ptr().cast_mut(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            null_mut(),
            null_mut(),
            new,
            null_mut(),
        )
    };
    if status != ERROR_SUCCESS {
        return Err(format!(
            "cannot set the ACL of {} (error {status})",
            path.display()
        ));
    }
    Ok(())
}

/// Confines the command as `restrictions` say, runs it, and returns its exit code.
///
/// # Errors
/// Any Win32 failure; the command has then not run (or, for the last steps, has been stopped).
pub fn run(restrictions: &WindowsRestrictions, command: &[OsString]) -> Result<u32, String> {
    let mut raw = null_mut();
    // SAFETY: the current process pseudo handle; `raw` receives an owned token.
    if unsafe {
        OpenProcessToken(
            GetCurrentProcess(),
            TOKEN_DUPLICATE
                | TOKEN_QUERY
                | TOKEN_ASSIGN_PRIMARY
                | TOKEN_ADJUST_DEFAULT
                | TOKEN_ADJUST_SESSIONID,
            &mut raw,
        )
    } == 0
    {
        return Err(last_error("OpenProcessToken"));
    }
    let own = Handle(raw);

    // user SID -> capability SID
    let user = token_info(own.0, TokenUser)?;
    // SAFETY: the buffer starts with a TOKEN_USER.
    let user_sid = unsafe { (*user.as_ptr().cast::<TOKEN_USER>()).User.Sid };
    let capability = sid_from_string(&winargs::capability_sid(&sid_to_string(user_sid)?))?;
    let everyone = sid_from_string("S-1-1-0")?;

    // the logon SID of this session (a restricting SID is needed for the window station and desktop)
    let groups = token_info(own.0, TokenGroups)?;
    // SAFETY: the buffer starts with a TOKEN_GROUPS whose array holds `GroupCount` entries.
    let logon = unsafe {
        let g = &*groups.as_ptr().cast::<TOKEN_GROUPS>();
        std::slice::from_raw_parts(g.Groups.as_ptr(), g.GroupCount as usize)
            .iter()
            .find(|g| g.Attributes & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID)
            .map(|g| g.Sid)
    }
    .ok_or("the token has no logon SID")?;

    // ACLs: write on the writable roots, no write on the protected names (a deny is read before an allow)
    let write = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;
    for root in &restrictions.write_roots {
        add_to_dacl(
            root,
            &[entry(
                capability.0,
                GRANT_ACCESS,
                write,
                SUB_CONTAINERS_AND_OBJECTS_INHERIT,
            )],
        )?;
    }
    for path in &restrictions.protected {
        let inherit = if path.is_dir() {
            SUB_CONTAINERS_AND_OBJECTS_INHERIT
        } else {
            0
        };
        add_to_dacl(
            path,
            &[entry(
                capability.0,
                DENY_ACCESS,
                FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD,
                inherit,
            )],
        )?;
    }

    // the restricted token
    let mut restricting = [
        SID_AND_ATTRIBUTES {
            Sid: capability.0,
            Attributes: 0,
        },
        SID_AND_ATTRIBUTES {
            Sid: logon,
            Attributes: 0,
        },
        SID_AND_ATTRIBUTES {
            Sid: everyone.0,
            Attributes: 0,
        },
    ];
    let mut restricted = null_mut();
    // SAFETY: `restricting` holds three valid SIDs that outlive the call.
    if unsafe {
        CreateRestrictedToken(
            own.0,
            DISABLE_MAX_PRIVILEGE | WRITE_RESTRICTED,
            0,
            null(),
            0,
            null(),
            restricting.len() as u32,
            restricting.as_mut_ptr(),
            &mut restricted,
        )
    } == 0
    {
        return Err(last_error("CreateRestrictedToken"));
    }
    let token = Handle(restricted);

    // objects the command creates (pipes, events) must be usable by the restricting SIDs too
    let entries = [
        entry(capability.0, GRANT_ACCESS, GENERIC_ALL, 0),
        entry(logon, GRANT_ACCESS, GENERIC_ALL, 0),
        entry(everyone.0, GRANT_ACCESS, GENERIC_ALL, 0),
    ];
    let mut default_dacl: *mut ACL = null_mut();
    // SAFETY: valid entries, no old ACL; the result is freed by `Local`.
    let status = unsafe {
        SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            null(),
            &mut default_dacl,
        )
    };
    let _default_dacl = Local(default_dacl.cast());
    if status != ERROR_SUCCESS {
        return Err(format!("cannot build the default ACL (error {status})"));
    }
    let info = TOKEN_DEFAULT_DACL {
        DefaultDacl: default_dacl,
    };
    // SAFETY: `info` is a TOKEN_DEFAULT_DACL of the size given.
    if unsafe {
        SetTokenInformation(
            token.0,
            TokenDefaultDacl,
            std::ptr::from_ref(&info).cast(),
            std::mem::size_of::<TOKEN_DEFAULT_DACL>() as u32,
        )
    } == 0
    {
        return Err(last_error("SetTokenInformation"));
    }

    // the job: the command and what it starts end with the helper
    // SAFETY: plain calls; the limit structure is zeroed and then set.
    let job = unsafe { CreateJobObjectW(null(), null()) };
    if job.is_null() {
        return Err(last_error("CreateJobObjectW"));
    }
    let job = Handle(job);
    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    // SAFETY: `limits` has the size given.
    if unsafe {
        SetInformationJobObject(
            job.0,
            JobObjectExtendedLimitInformation,
            std::ptr::from_ref(&limits).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    } == 0
    {
        return Err(last_error("SetInformationJobObject"));
    }

    // start it suspended, put it in the job, then let it run
    let args: Vec<Vec<u16>> = command.iter().map(|a| a.encode_wide().collect()).collect();
    let mut line = winargs::command_line(&args);
    line.push(0);
    // SAFETY: plain calls; the standard handles are inherited as they are.
    let mut startup: STARTUPINFOW = unsafe { std::mem::zeroed() };
    startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    startup.dwFlags = STARTF_USESTDHANDLES;
    unsafe {
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
        startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    }
    // SAFETY: zeroed output structure.
    let mut process: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: `line` is mutable and NUL terminated; the structures are valid for the call.
    if unsafe {
        CreateProcessAsUserW(
            token.0,
            null(),
            line.as_mut_ptr(),
            null(),
            null(),
            1,
            CREATE_SUSPENDED,
            null(),
            null(),
            &startup,
            &mut process,
        )
    } == 0
    {
        return Err(last_error("CreateProcessAsUserW"));
    }
    let child = Handle(process.hProcess);
    let thread = Handle(process.hThread);
    // SAFETY: both handles are valid.
    if unsafe { AssignProcessToJobObject(job.0, child.0) } == 0 {
        let error = last_error("AssignProcessToJobObject");
        // SAFETY: the child is suspended and must not run unconfined.
        unsafe { windows_sys::Win32::System::Threading::TerminateProcess(child.0, 125) };
        return Err(error);
    }
    // SAFETY: the thread is suspended; the wait is on the child.
    unsafe {
        ResumeThread(thread.0);
        WaitForSingleObject(child.0, INFINITE);
    }
    let mut code = 0u32;
    // SAFETY: the child has ended.
    if unsafe { GetExitCodeProcess(child.0, &mut code) } == 0 {
        return Err(last_error("GetExitCodeProcess"));
    }
    Ok(code)
}

/// Used by the helper binary: the arguments are the helper's, `OsString`s from the command line.
pub fn run_from_args(args: impl IntoIterator<Item = OsString>) -> Result<u32, String> {
    let (restrictions, command) = winargs::parse_args(args).map_err(|e| e.to_string())?;
    run(&restrictions, &command)
}
