"""Representative first-party Support contracts for catalog boundary fixtures."""

import yaml


def _support(repository, *, style="inline"):
    body = f"[Report a problem or ask a question]({repository}/issues/new/choose)\n[Existing issues]({repository}/issues)"
    component = {"component_id": "contact", "type": "markdown", "body": body}
    page = {"page_id": "support", "title": "Support", "project_scoped": False}
    files = {
        "ui/ui_manifest.yaml": yaml.safe_dump(
            {"version": "1", "pages": [{"ref": "pages/support.yaml"}]}
        )
    }
    if style == "content":
        page["components"] = [
            {"component_id": "contact", "type": "markdown", "content": body}
        ]
    elif style == "refs":
        page["components"] = [{"ref": "../components/contact.yaml"}]
        files["ui/components/contact.yaml"] = yaml.safe_dump(component)
    else:
        page["components"] = [component]
    files["ui/pages/support.yaml"] = yaml.safe_dump(page)
    return files
