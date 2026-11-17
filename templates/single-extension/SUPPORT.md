# Support page for maintained extensions

Every new Flow Steward maintained release must expose Support globally. In
`extension.yaml`, retain your other fields and declare:

```yaml
ui_manifest: ui/ui_manifest.yaml
vendor:
  name: Flow Steward
  support_url: https://github.com/Flow-Steward/<repo>/issues
```

Add the page to the existing `ui/ui_manifest.yaml` pages list:

```yaml
version: "1"
pages:
  - ref: pages/support.yaml
```

Ship `ui/pages/support.yaml` (replace `<repo>` with this extension's repository):

```yaml
page_id: support
title: Support
project_scoped: false
components:
  - component_id: support_contact
    type: markdown
    body: |
      Ask the Flow Steward developers a question, report a problem or request a feature.

      - [Report a problem or ask a question](https://github.com/Flow-Steward/<repo>/issues/new/choose)
      - [Browse existing issues](https://github.com/Flow-Steward/<repo>/issues)

      Include the extension and Flow Steward versions, what you did, the expected
      result and the actual error. Review diagnostics before sharing them.
      Issues are public: never post tokens, passwords, connection strings or customer data.
```

Existing markdown components may use `body` or `content`. A component can also
be referenced with `ref: ../components/support_contact.yaml`; ship the referenced
file. Keep refs inside the bundle, without cycles, and keep the Support page in
the registered pages list. Enable GitHub Issues and provide issue templates in
this repository. The catalog validates the archive's registered Support content
before it records a new release; existing immutable releases are not rewritten.

Describe the author as Flow Steward. A provider's logo or API integration does
not imply that the provider authors, certifies or endorses this extension.
The catalog's Verified badge is curated separately for exact tested releases.
