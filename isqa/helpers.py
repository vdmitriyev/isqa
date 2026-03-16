import os
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

import gitlab
import typer
from gitlab.v4.objects import Project
from rich.text import Text

from isqa.common import __save_json__
from isqa.configs import console, gitlab_auth_object, logger, settings
from isqa.constants import ISSUES_REORDER_ATTEMPT_SLEEP_SECONDS
from isqa.html import convert_to_html_list


def __check_and_fail__(key, message: str):
    if key is None:
        logger.error(message)
        logger.error(traceback.format_exc())
        console.print(Text(f"❌ ERROR: {message}", style="bold red"))
        raise typer.Exit(code=1)


def __print_and_fail__(message: str):
    logger.error(message)
    logger.error(traceback.format_exc())
    console.print(Text(f"❌ ERROR: {message}", style="bold red"))
    raise typer.Exit(code=1)


def get_gitlab_credentials_envs():

    GITLAB_URL = os.environ.get("GITLAB_URL")
    __check_and_fail__(GITLAB_URL, "No Gitlab URL. Set 'GITLAB_URL' in your .env file.")

    REPO_ID = os.environ.get("GITLAB_PROJECT_ID")
    __check_and_fail__(
        REPO_ID,
        "No repository ID or path was provided. Set 'GITLAB_PROJECT_ID' in your .env file.",
    )

    GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")
    __check_and_fail__(
        REPO_ID, "No token was provided. Set 'GITLAB_TOKEN' in your .env file."
    )

    if settings.verbose:
        console.print("Gitlab: ", Text(GITLAB_URL, style="bold yellow"))
        console.print("Repository:", Text(REPO_ID, style="bold yellow"))

    return GITLAB_URL, REPO_ID, GITLAB_TOKEN


def get_gitlab_project(repo_id: str, gitlab_url: str, token: str):
    """Initializes GitLab connection and retrieves the project object."""

    try:
        console.print(
            "Connecting to GitLab instance at: ",
            Text(f"{gitlab_url}", style="yellow bold"),
        )
        gl = gitlab.Gitlab(gitlab_url, private_token=token)
        gl.auth()

        global gitlab_auth_object
        gitlab_auth_object = gl

        project = gl.projects.get(repo_id)
        return project

    except gitlab.exceptions.GitlabAuthenticationError:
        __print_and_fail__(
            "Authentication failed. Check your URL and Personal Access Token."
        )
    except gitlab.exceptions.GitlabGetError:
        __print_and_fail__(
            f"Project with ID/Path '{repo_id} not found on {gitlab_url}."
        )
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    return None


def get_user_email(assignee_id: id):

    try:
        # FIXME: make a proper re-usage of the Gitlab session
        global gitlab_auth_object
        user = gitlab_auth_object.users.get(assignee_id)
        if len(user.public_email) == 0:
            return None
        return user.public_email

    except gitlab.exceptions.GitlabAuthenticationError:
        __print_and_fail__(
            "Authentication failed. Check your URL and Personal Access Token."
        )
    except Exception as e:
        __print_and_fail__(f"An unexpected error occurred: {e}")

    return None


def __print_on_dry_run_mode__(message: str):
    console.print(
        Text("✅", style="bold green"),
        "Dry run mode:",
        Text("enabled", style="bold green"),
        ". Message: ",
        Text(message, style="bold blue"),
    )


def print_issue_to_console(issue, due_date=None):
    iid = issue.get_id()
    assignee, assignee_email = get_assignee_data(issue)
    if not assignee:
        assignee = ""
    if not assignee_email:
        assignee_email = ""

    console.print(
        Text(f"{iid}", style="blue"),
        "\t",
        Text(issue.title, style="bold white"),
        Text(assignee, style="yellow"),
        Text(assignee_email, style="green"),
        end=None,
    )
    if due_date is not None:
        console.print(Text(f" {due_date}", style="bold red"), end=None)
    console.print()


def send_notification_from_cli(
    notify_admin: bool,
    notify_assignee: bool,
    issues_with_problems: list,
    repo_name: str,
    send_emain_func,
):
    """Abstraction function to send emails from CLI and set some parameters

    Args:
        notify_admin (bool): _description_
        notify_assignee (bool): _description_
        issues_with_problems (list): _description_
        repo_name (str): _description_
        send_emain_func (_type_): _description_
    """

    if notify_admin:
        user_name, user_email = "Admin", os.environ.get("EMAIL_ADMIN_TO_NOTIFY")
        issues_found = issues_with_problems[user_email]
        if not settings.dry_run:
            send_emain_func(
                user_email,
                user_name,
                repository_name=repo_name,
                issues_block=convert_to_html_list(issues_found),
            )
            console.print(Text("\nEmail has been sent.", style="bold green"))
        else:
            __print_on_dry_run_mode__("no email will be send")
    elif notify_assignee:
        for key, items in issues_with_problems.items():
            user_name, user_email = items[0]["assignee"], key
            issues_found = issues_with_problems[key]
            if not settings.dry_run:
                send_emain_func(
                    user_email,
                    user_name,
                    repository_name=repo_name,
                    issues_block=convert_to_html_list(issues_found),
                )
                console.print(Text("\nEmail has been sent.", style="bold green"))
            else:
                __print_on_dry_run_mode__("no email will be send")
    else:
        console.print(Text("\nNo one will be notified this time.", style="bold yellow"))


def get_assignee_data(issue):
    assignee, assignee_email = None, None
    if issue.assignee is not None:
        assignee = issue.assignee["name"]
        assignee_email = get_user_email(issue.assignee["id"])
    return assignee, assignee_email


def check_if_label_exists(project, label_name: str):
    """
    Checks if a label with the given name exists in the GitLab project.

    Args:
        project (gitlab.v4.objects.Project): The python-gitlab Project object.
        label_name (str): The name of the label to check.

    Returns:
        bool: True if the label exists, False otherwise.
    """
    try:
        project.labels.get(label_name)
        return True
    except gitlab.GitlabGetError:
        __print_and_fail__(f"Label with name '{label_name}' not found.")
    except Exception as e:
        __print_and_fail__("An unexpected error occurred")


def get_board_id_by_name(project: Project, board_name: str) -> Optional[int]:
    """
    Finds a GitLab board's ID within a project based on its name.

    Since the GitLab API does not support getting a board by name directly,
    this function fetches all boards for the project and searches the list.

    Args:
        project: The GitLab Project object (e.g., gl.projects.get(project_id)).
        board_name: The exact name of the board to find (case-sensitive).

    Returns:
        The integer ID of the board if found, otherwise None.
    """

    try:
        all_boards = project.boards.list(all=True)
        found_board = next(
            (board for board in all_boards if board.name == board_name), None
        )

        if found_board:
            board_id = found_board.id
            return board_id
        else:
            return None

    except gitlab.exceptions.GitlabError as e:
        __print_and_fail__("Error fetching boards from GitLab.")
    except Exception as e:
        __print_and_fail__("An unexpected error occurred")

    return None


def sort_issues_in_label(project, list_label_name: str, desc: bool = False):

    future_date = datetime.now() + timedelta(days=365 * 10)

    # this gets issues from the
    label_issues = project.issues.list(
        labels=[list_label_name],
        state="opened",
        get_all=True,
        order_by="relative_position",
        sort="asc",
    )

    issue_ids = []

    if len(label_issues) in [0, 1]:
        return fully_sorted

    for index, issue in enumerate(label_issues):
        if issue.due_date:
            due_date = datetime.strptime(issue.due_date, "%Y-%m-%d").date()
        else:
            due_date = (future_date + timedelta(days=issue.get_id())).date()

        issue_ids.append(
            {"iid": issue.get_id(), "position": issue.id, "dueDate": due_date}
        )

    sorted_issue_ids = sorted(issue_ids, key=lambda x: x["dueDate"], reverse=False)

    if desc:
        sorted_issue_ids = sorted(issue_ids, key=lambda x: x["dueDate"], reverse=True)

    if settings.verbose:
        print(f"issue_ids: \n {issue_ids}\n sorted_issue_ids:\n{sorted_issue_ids}")

    fully_sorted = True
    for index in range(len(sorted_issue_ids)):
        if issue_ids[index]["iid"] != sorted_issue_ids[index]["iid"]:
            fully_sorted = False
            break

    if fully_sorted:
        return fully_sorted

    for index, item in enumerate(sorted_issue_ids):
        if index + 1 < len(sorted_issue_ids):
            target_issue = project.issues.get(item["iid"])
            next_issue = sorted_issue_ids[index + 1]
            if not settings.dry_run:
                target_issue.reorder(move_after_id=next_issue["position"])
                target_issue.save()
            else:
                console.print(
                    Text("Ignoring re-oder command for the issues", style="bold yellow")
                )

    # last element
    target_issue = project.issues.get(sorted_issue_ids[-2]["iid"])
    next_issue = sorted_issue_ids[-1]
    if not settings.dry_run:
        target_issue.reorder(move_after_id=next_issue["position"])
        target_issue.save()
    else:
        console.print(
            Text("Ignoring re-oder command for the issues", style="bold yellow")
        )

    time.sleep(ISSUES_REORDER_ATTEMPT_SLEEP_SECONDS)

    return fully_sorted


def print_issues_in_label(label_issues: str, label_name: str):
    console.print(
        Text("\n⚙️", style="bold cyan"),
        "Listing issues of the label:",
        Text(label_name, style="bold yellow"),
    )
    for _, issue in enumerate(label_issues):
        print_issue_to_console(issue)
