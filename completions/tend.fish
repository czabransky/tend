# fish completions for tend

set -l commands run ls logs open rename stop restart rm

complete -c tend -f
complete -c tend -s h -l help -d "Show help"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -l version -d "Show the version"

complete -c tend -n "not __fish_seen_subcommand_from $commands" -a run -d "Start a command in the background"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a ls -d "List jobs"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a logs -d "Print a job's log"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a open -d "Open the job's local URL"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a rename -d "Rename a job"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a stop -d "Stop jobs (compose: down)"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a restart -d "Restart jobs (compose: down, then up)"
complete -c tend -n "not __fish_seen_subcommand_from $commands" -a rm -d "Stop jobs and forget them"

# Job names, with each job's state and command as the description.
complete -c tend -n "__fish_seen_subcommand_from logs open rename stop restart rm" -a "(tend _complete jobs)"

# The current directory's package.json scripts, .csproj files and compose files, as one argument each.
complete -c tend -n "__fish_seen_subcommand_from run" -a "(tend _complete run)"
complete -c tend -n "__fish_seen_subcommand_from run" -s n -l name -x -d "Job name"
complete -c tend -n "__fish_seen_subcommand_from run" -l keep-alive -d "Start it again when it crashes"

complete -c tend -n "__fish_seen_subcommand_from ls" -l json -d "JSON for other tools"
complete -c tend -n "__fish_seen_subcommand_from logs" -s f -l follow -d "Keep printing new lines"
complete -c tend -n "__fish_seen_subcommand_from logs" -s l -l lines -x -d "Lines to print"
complete -c tend -n "__fish_seen_subcommand_from stop" -s v -l volumes -d "Compose jobs: down -v"
complete -c tend -n "__fish_seen_subcommand_from open" -l port -x -d "Open the job's URL on this port"
