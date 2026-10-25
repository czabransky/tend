# Ideas

Things to build later, roughly in order. Move an item out when it's built.

- **Project profiles.** A jobs file per project, with `tend up [profile]` and `tend down`, so one
  command starts a whole stack (for example local, debuggable, staging). On hold until the
  design questions below have answers.
- **Explicit dependencies.** `tend run --after pf-db`, for orders the compose-first rule can't
  express, such as one app waiting for another.
- **Readiness for apps.** Wait until an app listens on its port before starting the next job, as
  group starts already do for compose containers.
- **Log search.** A key in the manager to open the focused log in `$PAGER` or the editor.
- **Linux backend.** systemd user services in place of launchd.
- **Release.** Tag a version, give the Homebrew formula a stable `url`, and consider nixpkgs and
  homebrew-core once it's out of beta.

## Profiles: open questions

- Where the file lives (`tend.json` at the project root?) and whether it's committed.
- What a profile changes: which jobs run, their commands, their environment, or all three.
- Whether profiles inherit from a base, so `debuggable` only overrides the API's command.
- How `tend up staging` relates to jobs already running from another profile.
