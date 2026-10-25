# tend

`npm run dev` in a terminal stops when the terminal closes. Backgrounded with `&`, it leaves no
log to find, and killing the pid you have stops the `npm` wrapper but leaves its `node` child
holding the port. `tend` runs dev commands as launchd jobs instead: they keep running after the
terminal closes, their output goes to a log, and stopping one stops its whole process group.

macOS only.

## Install

Homebrew:

```sh
brew tap czabransky/tend https://github.com/czabransky/tend
brew install --HEAD tend
```

Nix (flake):

```sh
nix profile install github:czabransky/tend
```

Or copy `tend` onto your PATH: it's one Python file using only the standard library.

## Usage

```fish
tend run -- pnpm dev            # job named after the current directory; -n picks a name
tend run                        # pick a package.json script, .csproj or compose file in fzf
tend run -- docker compose up
tend                            # manage jobs in fzf with a live log preview
tend ls --json                  # for other tools, e.g. a dashboard
tend open [name]                # open the URL the job logged in the browser
tend logs -f | stop | restart | rm [name]
tend stop -v [name]             # compose jobs: down -v
tend rename name [new]          # a running job restarts under the new name
tend restart 'pf*'              # patterns; quote them so the shell doesn't expand them
```

Commands that take a name use the current directory's job without one, or open an fzf picker.

## Job manager

`tend` with no arguments opens the job list in fzf, with the focused job's log on the right.

| Key | Action |
| --- | --- |
| enter | Follow the log in the terminal |
| ctrl-o | Open the job's URL |
| ctrl-e | Rename the job in place; enter applies, esc cancels |
| ctrl-s | Stop (compose: `down`) |
| ctrl-r | Restart (compose: `down`, then `up`) |
| ctrl-x | Remove the job and its log |
| tab, ctrl-a | Mark a job, mark all; ctrl-s, ctrl-r and ctrl-x act on the marked jobs |

## How it works

Each job is a plist in `~/.local/state/tend/`, bootstrapped into the user's GUI launchd domain
with the label `local.tend.<name>`. It runs the command with `/bin/sh` in the directory where
you ran `tend run`, with that terminal's PATH and locale. When direnv is installed, the command
runs through `direnv exec`, so the directory's `.envrc` applies. Restarts keep the saved PATH;
run `tend run` again to pick up a changed one. Output goes to `~/Library/Logs/tend/<name>.log`.
Nothing starts at login, and a crashed job stays down.

Stopping a job unloads it from launchd, which sends `SIGTERM` and then kills what's left of its
process group, including the `node` or app process a wrapper like `npm` or `dotnet run` started.

A plain `docker compose ... up` command is a compose job. `stop` runs `docker compose ... down`
with the same global flags, launchd gives compose 120 seconds to stop its containers, and its
ports come from `docker ps`.

With several jobs, stop and remove take compose jobs last. Restart stops the whole group, then
starts compose jobs first and waits until their containers are up, and healthy where they have a
healthcheck, before starting the rest.

## Colors

The default theme is Catppuccin Frappé. Set `TEND_THEME=terminal` to use your terminal's own 16
colors instead; fzf then keeps the colors from your `FZF_DEFAULT_OPTS`. `TEND_FZF_COLORS` is
passed to fzf as one more `--color` after the theme's, to change parts of it:

```fish
set -gx TEND_FZF_COLORS 'pointer:#f4b8e4,label:#babbf1'
```

`NO_COLOR` turns colors off in `tend ls`.

## Requirements

- macOS (launchd).
- Python 3.9 or later, standard library only. The Xcode Command Line Tools provide one at
  `/usr/bin/python3`, and Homebrew requires them, so a Homebrew install needs nothing more.
- fzf 0.73 or later, for the job manager and pickers. The Homebrew and Nix packages install it.
- Optional: direnv, to apply each directory's `.envrc`; docker, for compose jobs.

## Development

```sh
python3 -m unittest discover tests
```

The tests replace launchd, lsof, ps and docker with fakes and use a temporary HOME.

## License

Public domain, under the [Unlicense](LICENSE).
