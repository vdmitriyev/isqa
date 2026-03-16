import os
import traceback
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import gitlab
import typer
from dotenv import load_dotenv
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated

from isqa.common import __save_json__
from isqa.configs import console, logger, settings
from isqa.constants import ISSUES_REORDER_ATTEMPT_SLEEP_SECONDS
from isqa.exceptions import IsQAGitlabNoRepository, IsQAWrongCLIParams
from isqa.helpers import (
    __print_and_fail__,
    check_if_label_exists,
    get_assignee_data,
    get_board_id_by_name,
    get_gitlab_credentials_envs,
    get_gitlab_project,
    print_issue_to_console,
    print_issues_in_label,
    send_notification_from_cli,
    sort_issues_in_label,
)
from isqa.notifier import (
    send_email_due_date_expired,
    send_email_missing_assignee,
    send_email_missing_label,
)
from isqa.version import package_summary, package_version

app = typer.Typer(
    help="`isqa` utility for quality assurance of GitLab issues. Helps managing issues of a repository."
)


class MigrationConditionChoice(str, Enum):
    due_date = "due-date"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-d",
            help="Simulate execution without making changes.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose outputs.",
        ),
    ] = False,
    env_file: Annotated[
        Path,
        typer.Option(
            "--env-file",
            "-e",
            help="Specify a path to a .env file to load environment variables.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Enable verbose outputs.",
        ),
    ] = False,
) -> None:
    """
    This function runs *before* any other command (subcommand)
    or when the app is called without a subcommand.
    """
    settings.dry_run = dry_run
    settings.verbose = verbose

    if settings.verbose:
        console.print(
            Text("✅", style="bold green"),
            "Verbose mode:",
            Text("enabled", style="bold green"),
        )
        console.print(
            Text("✅", style="bold green"),
            "Dry run mode:",
            Text(
                f"{settings.dry_run}",
                style=f"bold {"red" if not settings.dry_run else "green"}",
            ),
        )
    elif settings.dry_run:
        console.print(
            Text("✅", style="bold green"),
            "Dry run mode:",
            Text("enabled", style="bold green"),
        )

    from isqa.constants import DEFAULT_ENV_EXTRA_CONFIG

    load_dotenv(DEFAULT_ENV_EXTRA_CONFIG, override=True)

    if env_file:
        console.print(
            "Loading environment variables from:",
            Text(f"{env_file}", style="bold blue"),
        )
        success = load_dotenv(env_file, override=True)
        if not success:
            typer.echo(f"Warning: Could not load variables from {env_file}", err=True)
    else:
        load_dotenv()

    if version:
        if settings.verbose:
            table = Table()
            table.add_column("Field", justify="right", style="cyan", no_wrap=True)
            table.add_column("Value", justify="left", style="yellow", no_wrap=True)
            summary = package_summary()
            for item in summary:
                table.add_row(item["field"], item["value"])
            console.print(table)
        else:
            console.print(f"{package_version()}", style="yellow")
        exit(0)

    # If a subcommand was provided, don't exit; continue to the subcommand.
    # Otherwise, Typer will handle exiting or showing the help page.
    if ctx.invoked_subcommand is not None:
        return


@app.command()
def list_issues(
    state: str = typer.Option(
        "opened",
        "--state",
        "-s",
        help="Filter issues by state: opened, closed, or all.",
    ),
):
    """
    Lists all issues for the repository.
    """

    gitlab_url, repo_id, token = get_gitlab_credentials_envs()

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if not project:
        raise IsQAGitlabNoRepository(
            f"Unable to connect to Gitlab repository: {repo_id}"
        )

    console.print(
        "Get",
        Text(state, style="bold yellow"),
        "issues for project:",
        Text(repo_id, style="bold green"),
    )

    try:

        issues = project.issues.list(state=state, get_all=True, iterator=True)
        issue_data = []
        for issue in issues:
            issue_data.append(issue.asdict())
            print_issue_to_console(issue)

        if not issue_data:
            console.print(
                Text("No issues found for the specified criteria.", style="bold blue")
            )
            return

        console.print("\nTotal issues:", Text(f"{len(issue_data)}", style="bold cyan"))

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(issue_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def list_board_issues(
    board_id: Optional[int] = typer.Option(
        None,
        "--board-id",
        "-b",
        help="Specific Board ID to inspect. Defaults to the first board found.",
    ),
    board_name: Optional[str] = typer.Option(
        None,
        "--board-name",
        "-n",
        help="Specific Board name to inspect. Defaults to the first board found.",
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="Specific label name to show. Defaults to all labels found.",
    ),
    without_labels: Annotated[
        bool,
        typer.Option(
            "--without-labels",
            "-w",
            help="Lists also issues without labels.",
        ),
    ] = False,
):
    """
    Lists all issues with a label used as columns on a GitLab board.
    Only the first board is processed. A specific board ID could be provided.
    """
    gitlab_url, repo_id, token = get_gitlab_credentials_envs()

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if label is not None:
        check_if_label_exists(project, label)

    try:

        console.print("\nFetching project boards...")
        boards = project.boards.list()

        if not boards:
            console.print(
                Text("No Issue Boards found for this project.", style="bold yellow")
            )
            return

        board = None
        if board_name:
            board_id = get_board_id_by_name(project, board_name)

        if board_id:
            try:
                board = project.boards.get(board_id)
            except gitlab.exceptions.GitlabGetError:
                __print_and_fail__(f"Board with ID '{board_id}' not found.")
        else:
            board = boards[0]
            console.print(
                f"Using the first board found (ID: {board.id}):",
                Text(board.name, style="bold green"),
            )

        lists = board.lists.list()
        if not lists:
            console.print(
                Text(f"No lists found for board {board.name}.", style="bold yellow")
            )
            return

        board_data = {
            "board_id": board.id,
            "board_name": board.name,
            "lists": {},
        }

        boards_labels = set()
        for list_obj in lists:
            b_list = board.lists.get(list_obj.id)
            list_label_name = b_list.label["name"]

            if label is not None and list_label_name.lower() != label.lower():
                continue

            boards_labels.add(list_label_name)
            board_data["lists"][list_label_name] = []
            label_issues = project.issues.list(
                labels=[list_label_name], state="opened", get_all=True, iterator=True
            )

            print_issues_in_label(
                label_issues,
                list_label_name,
            )

            for _, issue in enumerate(label_issues):
                board_data["lists"][list_label_name].append(issue.asdict())

        # print issues without labels
        if without_labels:
            issues_without_labels = []
            issues_without_labels_label = "issues-without-labels"
            board_data["lists"][issues_without_labels_label] = []
            all_issues = project.issues.list(
                labels=[], state="opened", get_all=True, iterator=True
            )
            for issue in all_issues:
                if len(boards_labels.intersection(issue.labels)) == 0:
                    issues_without_labels.append(issue)
                    board_data["lists"][issues_without_labels_label].append(
                        issue.asdict()
                    )

            print_issues_in_label(
                issues_without_labels,
                label_name=issues_without_labels_label,
            )

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(board_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def migrate_issues(
    state: str = typer.Option(
        "opened",
        "--state",
        "-s",
        help="Filter issues by state: opened, closed, or all.",
    ),
    from_label: Optional[str] = typer.Option(
        None, "--from-label", "-f", help="Specific label name to migrate `from`."
    ),
    to_label: Optional[str] = typer.Option(
        None, "--to-label", "-t", help="Specific label name to migrate `to`."
    ),
    check_condition: Optional[MigrationConditionChoice] = typer.Option(
        None,
        "--check-condition",
        help="Specific condition to check before migrating labels.",
    ),
):
    """
    Migrated issues from one label to another label. Each issue must meet specific conditions (e.g., 'due-date').
    """

    gitlab_url, repo_id, token = get_gitlab_credentials_envs()

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if not project:
        raise IsQAGitlabNoRepository(
            f"Unable to connect to Gitlab repository: {repo_id}"
        )

    check_if_label_exists(project, from_label)
    check_if_label_exists(project, to_label)

    if not check_condition:
        raise IsQAWrongCLIParams("--check-condition must be provided")

    console.print(
        "Get",
        Text(state, style="bold yellow"),
        "issues for project:",
        Text(repo_id, style="bold green"),
    )

    try:

        issues = project.issues.list(state=state, get_all=True, iterator=True)
        issue_data = []

        now = datetime.now(timezone.utc).date()

        for issue in issues:
            if issue.labels is not None and len(issue.labels) != 0:

                current_labels = issue.labels
                new_labels = [label for label in current_labels if label != from_label]

                if new_labels != current_labels:
                    condition_satisfied = False
                    # check due-date condition
                    if check_condition.value == "due-date":
                        if issue.due_date:
                            due_date = datetime.strptime(
                                issue.due_date, "%Y-%m-%d"
                            ).date()
                            if due_date < now:
                                condition_satisfied = True

                    if condition_satisfied:
                        print_issue_to_console(issue)
                        issue_data.append(issue.asdict())
                        new_labels.append(to_label)
                        if not settings.dry_run:
                            issue.labels = new_labels
                            issue.save()
                        else:
                            console.print("No labels will be migrated")

                        console.print(
                            Text("✅", style="bold green"),
                            Text(
                                f"Issue labels updated successfully from -> ",
                                style="bold white",
                            ),
                            Text(f"'{from_label}'", style="bold blue"),
                            "to",
                            Text(f"'{to_label}'", style="bold green"),
                        )

        if not issue_data:
            console.print(
                Text("No issues found for the specified criteria.", style="bold blue")
            )
            return

        console.print("\nTotal issues:", Text(f"{len(issue_data)}", style="bold cyan"))

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(issue_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def sort_board_issues(
    board_id: Optional[int] = typer.Option(
        None,
        "--board-id",
        "-b",
        help="Specific Board ID to inspect. Defaults to the first board found.",
    ),
    board_name: Optional[str] = typer.Option(
        None,
        "--board-name",
        "-n",
        help="Specific Board name to inspect. Defaults to the first board found.",
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="Specific label name to be sorted. Defaults to all labels found.",
    ),
    desc: Annotated[
        bool,
        typer.Option(
            "--descending",
            "-desc",
            help="Sort issues in descending order by due date",
        ),
    ] = False,
):
    """
    Sorts all issues with a given label of a particular GitLab board.
    Only the first board is processed. A specific board ID could be provided.
    """
    gitlab_url, repo_id, token = get_gitlab_credentials_envs()

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if label is not None:
        check_if_label_exists(project, label)

    try:

        console.print("\nFetching project boards...")
        boards = project.boards.list()

        if not boards:
            console.print(
                Text("No Issue Boards found for this project.", style="bold yellow")
            )
            return

        board = None
        if board_name:
            board_id = get_board_id_by_name(project, board_name)

        if board_id:
            try:
                board = project.boards.get(board_id)
            except gitlab.exceptions.GitlabGetError:
                __print_and_fail__(f"Board with ID '{board_id}' not found.")
        else:
            board = boards[0]
            console.print(
                f"Using the first board found (ID: {board.id}):",
                Text(board.name, style="bold green"),
            )

        lists = board.lists.list()
        if not lists:
            console.print(
                Text(f"No lists found for board {board.name}.", style="bold yellow")
            )
            return

        for list_obj in lists:
            b_list = board.lists.get(list_obj.id)
            list_label_name = b_list.label["name"]

            if label is not None and label != list_label_name:
                continue

            console.print(
                Text("\n⚙️", style="bold cyan"),
                "Sorting issues of the label (part of board):",
                Text(list_label_name, style="bold yellow"),
            )

            label_issues = project.issues.list(
                labels=[list_label_name], state="opened", get_all=True, iterator=True
            )

            if len(label_issues) > 1:
                max_runs = len(label_issues) - 1
                estimate_time = max_runs * ISSUES_REORDER_ATTEMPT_SLEEP_SECONDS
                console.print(
                    Text("⚠️", style="bold yellow"),
                    "Estimated max sorting time (seconds): ",
                    Text(f"{estimate_time}", style="bold yellow"),
                )
                for index in range(max_runs):
                    if settings.verbose:
                        console.print(
                            "Running iteration: ",
                            Text(str(index + 1), style="bold yellow"),
                        )
                    if sort_issues_in_label(project, list_label_name, desc):
                        break
            else:
                console.print(Text(f"Nothing to sort here", style="bold white"))

            console.print(
                Text("✅", style="bold green"),
                Text(f"Successfully sorted issues for label:", style="bold white"),
                Text(f"{list_label_name}", style="bold green"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def check_due_date(
    state: str = typer.Option(
        "opened",
        "--state",
        "-s",
        help="Filter issues by state: opened, closed, or all.",
    ),
    notify_admin: bool = typer.Option(
        False,
        "--notify-admin",
        help="If set, notifies admin about issues with a past due date.",
    ),
    notify_assignee: bool = typer.Option(
        False,
        "--notify-assignee",
        help="If set, notifies assignee about issues with a past due date.",
    ),
):
    """
    Checks all issues if the 'due date' has passed. Optionally notifies the admin or assignee.
    """

    gitlab_url, repo_id, token = get_gitlab_credentials_envs()
    repo_name = repo_id

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
        repo_name = project.name
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if not project:
        raise IsQAGitlabNoRepository(
            f"Unable to connect to Gitlab repository: {repo_id}"
        )

    console.print(
        "Get",
        Text(state, style="bold yellow"),
        "issues for project:",
        Text(repo_id, style="bold green"),
    )

    try:
        issues = project.issues.list(state=state, get_all=True, iterator=True)
        issue_data = []

        now = datetime.now(timezone.utc).date()
        issues_with_problems = {}
        for issue in issues:
            issue_data.append(issue.asdict())
            try:
                if issue.due_date:
                    due_date = datetime.strptime(issue.due_date, "%Y-%m-%d").date()
                    if due_date < now:
                        print_issue_to_console(issue, due_date=due_date)

                        if notify_admin:
                            assignee, assignee_email = "Admin", os.environ.get(
                                "EMAIL_ADMIN_TO_NOTIFY"
                            )
                            if assignee_email not in issues_with_problems:
                                issues_with_problems[assignee_email] = []
                            issues_with_problems[assignee_email].append(
                                {
                                    "link": issue.web_url,
                                    "title": issue.title,
                                    "assignee": assignee,
                                }
                            )

                        if notify_assignee:
                            assignee, assignee_email = get_assignee_data(issue)
                            if assignee is None or assignee_email is None:
                                assignee, assignee_email = "Admin", os.environ.get(
                                    "EMAIL_ADMIN_TO_NOTIFY"
                                )
                            if assignee_email not in issues_with_problems:
                                issues_with_problems[assignee_email] = []
                            issues_with_problems[assignee_email].append(
                                {
                                    "link": issue.web_url,
                                    "title": issue.title,
                                    "assignee": assignee,
                                }
                            )

            except Exception:
                logger.error(traceback.format_exc())

        if len(issues_with_problems) > 0:
            send_notification_from_cli(
                notify_admin,
                notify_assignee,
                issues_with_problems,
                repo_name,
                send_email_due_date_expired,
            )
        else:
            console.print(
                Text("\nNo one will be notified this time.", style="bold yellow")
            )

        if not issue_data:
            console.print(
                Text("No issues found for the specified criteria.", style="bold yellow")
            )
            return

        console.print(
            "\nTotal issues:", Text(f"{len(issue_data)}", style="bold yellow")
        )

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(issue_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def check_missing_assignee(
    state: str = typer.Option(
        "opened",
        "--state",
        "-s",
        help="Filter issues by state: opened, closed, or all.",
    ),
    notify_admin: bool = typer.Option(
        False, "--notify-admin", help="If set, notifies admin about no assignee"
    ),
):
    """
    Checks all issues if the 'assignee' has not been set. Optionally notifies the admin.
    """

    gitlab_url, repo_id, token = get_gitlab_credentials_envs()
    repo_name = repo_id

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
        repo_name = project.name
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if not project:
        raise IsQAGitlabNoRepository(
            f"Unable to connect to Gitlab repository: {repo_id}"
        )

    console.print(
        "Get",
        Text(state, style="bold yellow"),
        "issues for project:",
        Text(repo_id, style="bold green"),
    )

    try:
        issues = project.issues.list(state=state, get_all=True, iterator=True)
        issue_data = []
        issues_with_problems = {}
        assignee, assignee_email = "Admin", os.environ.get("EMAIL_ADMIN_TO_NOTIFY")
        issues_with_problems[assignee_email] = []

        for issue in issues:
            issue_data.append(issue.asdict())
            try:
                if issue.assignee is None:
                    print_issue_to_console(issue)
                    issues_with_problems[assignee_email].append(
                        {
                            "link": issue.web_url,
                            "title": issue.title,
                            "assignee": assignee,
                        }
                    )
            except Exception:
                logger.error(traceback.format_exc())

        if len(issues_with_problems) > 0:
            send_notification_from_cli(
                notify_admin,
                False,
                issues_with_problems,
                repo_name,
                send_email_missing_assignee,
            )
        else:
            console.print(
                Text("\nNo one will be notified this time.", style="bold yellow")
            )

        if not issue_data:
            console.print(
                Text("No issues found for the specified criteria.", style="bold yellow")
            )
            return

        console.print(
            "\nTotal issues:", Text(f"{len(issue_data)}", style="bold yellow")
        )

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(issue_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


@app.command()
def check_missing_label(
    state: str = typer.Option(
        "opened",
        "--state",
        "-s",
        help="Filter issues by state: opened, closed, or all.",
    ),
    notify_admin: bool = typer.Option(
        False, "--notify-admin", help="If set, notifies admin about missing label."
    ),
    notify_assignee: bool = typer.Option(
        False,
        "--notify-assignee",
        help="If set, notifies assignee about missing label.",
    ),
):
    """
    Checks all issues if a label is missing. Optionally notifies the admin or assignee.
    """

    gitlab_url, repo_id, token = get_gitlab_credentials_envs()
    repo_name = repo_id

    try:
        project = get_gitlab_project(repo_id, gitlab_url, token=token)
        repo_name = project.name
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    if not project:
        raise IsQAGitlabNoRepository(
            f"Unable to connect to Gitlab repository: {repo_id}"
        )

    console.print(
        "Get",
        Text(state, style="bold yellow"),
        "issues for project:",
        Text(repo_id, style="bold green"),
    )

    try:
        issues = project.issues.list(state=state, get_all=True, iterator=True)
        issue_data = []
        issues_with_problems = {}

        for issue in issues:
            issue_data.append(issue.asdict())
            try:
                if issue.labels is None or len(issue.labels) == 0:
                    print_issue_to_console(issue)

                    if notify_admin:
                        assignee, assignee_email = "Admin", os.environ.get(
                            "EMAIL_ADMIN_TO_NOTIFY"
                        )
                        if assignee_email not in issues_with_problems:
                            issues_with_problems[assignee_email] = []
                        issues_with_problems[assignee_email].append(
                            {
                                "link": issue.web_url,
                                "title": issue.title,
                                "assignee": assignee,
                            }
                        )

                    if notify_assignee:
                        assignee, assignee_email = get_assignee_data(issue)
                        if assignee is None or assignee_email is None:
                            assignee, assignee_email = "Admin", os.environ.get(
                                "EMAIL_ADMIN_TO_NOTIFY"
                            )
                        if assignee_email not in issues_with_problems:
                            issues_with_problems[assignee_email] = []
                        issues_with_problems[assignee_email].append(
                            {
                                "link": issue.web_url,
                                "title": issue.title,
                                "assignee": assignee,
                            }
                        )

            except Exception:
                logger.error(traceback.format_exc())

        if len(issues_with_problems) > 0:
            send_notification_from_cli(
                notify_admin,
                notify_assignee,
                issues_with_problems,
                repo_name,
                send_email_missing_label,
            )
        else:
            console.print(
                Text("\nNo one will be notified this time.", style="bold yellow")
            )

        if not issue_data:
            console.print(
                Text("No issues found for the specified criteria.", style="bold yellow")
            )
            return

        console.print(
            "\nTotal issues:", Text(f"{len(issue_data)}", style="bold yellow")
        )

        if settings.verbose:
            console.print(
                "JSON have seen saved into: ",
                Text(__save_json__(issue_data), style="bold cyan"),
            )

    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    app()
