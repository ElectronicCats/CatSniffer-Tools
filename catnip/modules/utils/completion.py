"""``catnip completion`` - shell tab-completion installer.

Registered on the root group only on Linux/macOS, see section 3.2 of
``CLI_REFACTOR_PLAN.md``.
"""

import os
import platform
import sys

# External
import click

from .output import (
    print_success,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
    print_example,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def completion():
    """Install shell tab completion for catnip."""
    pass


@completion.command("install")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell to install completion for (auto-detected if omitted)",
)
def completion_install(shell):
    """Install tab completion for your shell.

    Run this once, then restart your shell (or source your rc file).

    \b
        catnip completion install          # auto-detect shell
        catnip completion install --shell zsh
    """
    if platform.system() == "Windows":
        print_error("Shell completion is not supported on Windows.")
        sys.exit(1)

    import subprocess as _sp
    from pathlib import Path

    # Auto-detect shell
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        if "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        elif "bash" in shell_env:
            shell = "bash"
        else:
            print_error("Could not detect shell. Use --shell bash|zsh|fish.")
            sys.exit(1)
        print_info(f"Detected shell: {shell}")

    env_var = "_CATNIP_COMPLETE"

    # Absolute path to this script and the Python interpreter running it.
    # We always want completions to call "python /abs/path/to/catnip.py" so
    # that they work regardless of whether catnip is on PATH.
    script_abs = str(Path(sys.argv[0]).resolve())
    python_abs = str(Path(sys.executable).resolve())
    # The full command string that the completion script will execute
    cmd_to_call = f"{python_abs} {script_abs}"

    if shell == "bash":
        target = (
            Path.home()
            / ".local"
            / "share"
            / "bash-completion"
            / "completions"
            / "catnip"
        )
        source_flag = "bash_source"
        rc_note = None
    elif shell == "zsh":
        target = Path.home() / ".zfunc" / "_catnip"
        source_flag = "zsh_source"
        rc_note = "fpath=(~/.zfunc $fpath)\nautoload -Uz compinit && compinit"
    elif shell == "fish":
        target = Path.home() / ".config" / "fish" / "completions" / "catnip.fish"
        source_flag = "fish_source"
        rc_note = None

    try:
        result = _sp.run(
            [python_abs, script_abs],
            env={**os.environ, env_var: source_flag},
            capture_output=True,
            text=True,
        )
        script = result.stdout
    except OSError as e:
        print_error(f"Failed to generate completion script: {e}")
        sys.exit(1)

    if not script.strip():
        print_error(
            "Empty completion script generated.\n"
            "Make sure you are running this command via:\n"
            f"  python {script_abs} completion install"
        )
        if result.stderr.strip():
            print_dim(result.stderr.strip())
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Post-process: replace the bare 'catnip' program name that Click      #
    # embeds in the script with the full "python /abs/path/catnip.py"      #
    # invocation.  We handle every pattern Click 7.x / 8.x can emit.      #
    # ------------------------------------------------------------------ #
    if shell == "zsh":
        # 1. #compdef directive — register for all the names a user might type
        script = script.replace(
            "#compdef catnip", "#compdef catnip catnip.py ./catnip.py"
        )
        # 2. The guard that aborts when the command is not found in $commands[].
        #    We neutralise it because we use an absolute path, not a PATH entry.
        script = script.replace(
            "(( ! $+commands[catnip] ))",
            "false",  # 'false' evaluates to 1 so the (( )) block never returns
        )
        # 3. The line that actually calls the program to obtain completions.
        #    Click 8 emits:  _CATNIP_COMPLETE=zsh_complete catnip
        script = script.replace(
            f"{env_var}=zsh_complete catnip", f"{env_var}=zsh_complete {cmd_to_call}"
        )
        # 4. The compdef registration at the bottom of the script
        script = script.replace(
            "compdef _catnip_completion catnip",
            f"compdef _catnip_completion catnip catnip.py ./catnip.py",
        )

        # 5. Append an explicit wrapper so that "python catnip.py <TAB>" and
        #    "./catnip.py <TAB>" also trigger completion.  zsh matches on the
        #    last component of $words[1], so we register a catch-all that
        #    delegates to our function.
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py' or './catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "  local script_name=${words[2]:t}  # basename of the script argument\n"
            "  if [[ $script_name == catnip.py ]]; then\n"
            f"    (( ! $+functions[_catnip_completion] )) && source {target}\n"
            '    words=(catnip "${words[@]:2}")\n'
            "    (( CURRENT-- ))\n"
            "    _catnip_completion\n"
            "  else\n"
            "    _files\n"
            "  fi\n"
            "}\n"
            "compdef _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "bash":
        # Click <=8.0 emits:  _CATNIP_COMPLETE=bash_complete catnip
        # Click >=8.1 emits:  _CATNIP_COMPLETE=bash_complete $1
        script = script.replace(
            f"{env_var}=bash_complete catnip", f"{env_var}=bash_complete {cmd_to_call}"
        )
        script = script.replace(
            f"{env_var}=bash_complete $1", f"{env_var}=bash_complete {cmd_to_call}"
        )
        # Register for both 'catnip' and 'catnip.py' (Click 8.1 adds -o nosort)
        script = script.replace(
            "complete -F _catnip_completion catnip",
            "complete -F _catnip_completion catnip catnip.py",
        )
        script = script.replace(
            "complete -o nosort -F _catnip_completion catnip",
            "complete -o nosort -F _catnip_completion catnip catnip.py",
        )
        # Append a wrapper that intercepts 'python catnip.py <TAB>'
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "    local cur script_arg\n"
            '    cur="${COMP_WORDS[COMP_CWORD]}"\n'
            '    script_arg="${COMP_WORDS[1]}"\n'
            '    if [[ "$(basename "$script_arg")" == "catnip.py" ]]; then\n'
            "        # Rebuild COMP_WORDS without the leading 'python' / path\n"
            '        local new_words=(catnip "${COMP_WORDS[@]:2}")\n'
            '        COMP_WORDS=("${new_words[@]}")\n'
            "        COMP_CWORD=$(( COMP_CWORD - 1 ))\n"
            "        _catnip_completion\n"
            "    fi\n"
            "}\n"
            "complete -F _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "fish":
        # Fish uses a different mechanism; just replace the bare program name.
        # Click <=8.0 puts it right after the env var, >=8.1 after COMP_CWORD.
        script = script.replace(
            f"{env_var}=fish_complete catnip", f"{env_var}=fish_complete {cmd_to_call}"
        )
        script = script.replace(
            "COMP_CWORD=(commandline -t) catnip)",
            f"COMP_CWORD=(commandline -t) {cmd_to_call})",
        )
        # Also complete when invoked as './catnip.py'
        script += (
            "\ncomplete --no-files --command catnip.py "
            '--arguments "(_catnip_completion)"\n'
        )

    # Write script
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
    except OSError as e:
        print_error(f"could not write completion script to {target}: {e}")
        sys.exit(1)
    print_success(f"Completion script written to: {target}")

    # zsh needs fpath entry in .zshrc
    if rc_note:
        zshrc = Path.home() / ".zshrc"
        try:
            existing = zshrc.read_text(encoding="utf-8") if zshrc.exists() else ""
        except OSError as e:
            print_error(f"could not read {zshrc}: {e}")
            sys.exit(1)
        if "~/.zfunc" not in existing and ".zfunc" not in existing:
            try:
                if zshrc.exists():
                    backup = zshrc.with_name(".zshrc.bak-catnip")
                    backup.write_text(existing, encoding="utf-8")
                with zshrc.open("a", encoding="utf-8") as f:
                    f.write(f"\n# catnip tab completion\n{rc_note}\n")
            except OSError as e:
                print_error(f"could not update {zshrc}: {e}")
                sys.exit(1)
            print_success(f"Added fpath entry to {zshrc}")
        else:
            print_dim("~/.zfunc already in fpath — skipping .zshrc edit")

    print_empty_line()
    if shell == "bash":
        print_info("Restart your shell or run:")
        print_example(f"source {target}")
    elif shell == "zsh":
        print_info("Restart your shell or run:")
        print_example("source ~/.zshrc && compinit -u")
    elif shell == "fish":
        print_info("Completion is active immediately in new fish sessions.")
