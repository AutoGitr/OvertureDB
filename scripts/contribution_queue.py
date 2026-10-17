"""Trusted main-only queue dispatcher."""

lazy import os

lazy from . import github, queue_git, queue_issues, queue_prs
lazy from .queue_state import Store


def main() -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Queue automation must run trusted main code")
    repo = os.environ["GITHUB_REPOSITORY"]
    bot_id = int(os.environ["QUEUE_BOT_ID"])
    app_id = int(os.environ["QUEUE_APP_ID"])
    if os.environ["QUEUE_APP_SLUG"] + "[bot]" != github.BOT_LOGIN:
        raise ValueError("Token belongs to a different installed app")
    # The token workflow resolves the installed app's bot user, not issue/PR labels.
    bot = github.api(f"users/{github.BOT_LOGIN}")
    if bot["id"] != bot_id or bot["type"] != "Bot":
        raise ValueError("Configured app bot identity does not match")
    store = Store()
    if identity := os.environ.get("QUEUE_RETRY"):
        if not queue_issues.can_write(repo, os.environ["GITHUB_ACTOR"]):
            raise ValueError("Write access is required to retry a request")
        request = next(r for r in store.state["requests"] if r["id"] == identity)
        queue_prs.retry(repo, request, store)
    _, entries = queue_git.main_snapshot(repo)
    queue_issues.sync(repo, entries, store, bot_id)
    if os.environ.get("QUEUE_IMPORT") == "true":
        revision = github.api("repos/LizardByte/ThemerrDB/commits/database")["sha"]
        store.enqueue("import", {"upstream": revision})
    queue_prs.protections(repo, app_id)
    queue_prs.tick(repo, store, bot_id)


if __name__ == "__main__":
    main()
