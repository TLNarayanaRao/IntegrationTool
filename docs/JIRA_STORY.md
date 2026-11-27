# Build or review an integration from a Jira story

Open **Jira Story** in the Studio ribbon under **AI**, alongside **AI Build** and **AI Catch**. From the welcome screen, select **Build from Jira story** to create a project.

1. Select **Paste story** and paste the description and acceptance criteria. To load a Jira Cloud issue, select **Read Jira Cloud issue**, enter its `https://<site>.atlassian.net/browse/<issue-key>` link, and click **Read issue**. To read a private issue, provide your Jira email and a site API token with issue access. Leave both credential fields blank for a public issue. For Jira Data Center or custom domains, paste the story.
2. Review the editable story text. Include the trigger, input and output contracts, operation and destination, field mappings, and expected behavior on failure. If acceptance criteria live in a separate Jira text field, enter its ID, such as `customfield_10042`, before reading the issue. You can also include issue type, status, and available parent and subtask summaries in the same read. You can remove any of this context before requesting a preview.
3. Choose one of the following targets.

| Target | Workflow |
| --- | --- |
| New project | Enter a project name and click **Generate preview**. Inspect the tasks, activity configuration, and proposed connections. Click **Create project** to open a separate project, then validate and save it. |
| Review existing flow | Select a task and click **Review flow**. Compare the story with the existing activities and transitions, then check the reported gaps. |
| Extend existing flow | Select a task and an unconditional success transition outside groups. Click **Generate preview** and inspect the proposed sequence. For each proposed connection, create the draft connection or reuse an existing connection of the same type when available. Click **Insert activities** to add the steps between the selected endpoints. Review mappings that use `${last}` because the preceding output on that path has changed. |

The existing-flow extension adds a linear sequence and any draft assets. Use Studio to make changes to existing activities, conditions, group membership, and error handling. Check generated connection settings, schemas and input mappings, then run **Validate Task** or **Validate Project** before using Run or Debug.

Select **Download review** to save the findings, proposed activity names, and selected connection names as JSON for a development handoff. The review file omits the Jira API token and connection configurations.

Without a configured AI provider, the local blueprint matches supported activity keywords such as `parse JSON`, `publish to Kafka`, and `HTTP request`. Its flow review checks matching activity operations. With a configured OpenAI provider, preview requests send the reviewed story text and selected task activity and transition metadata to that provider. The Jira token is used for the issue read and cleared from the dialog afterward. Use the story field for requirements and the Studio connection editor for secrets.

See the [Jira Cloud Get issue API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/#api-rest-api-3-issue-issueidorkey-get) for Jira issue access requirements.
