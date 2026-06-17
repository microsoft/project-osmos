# Parsing Fabric URLs to extract IDs

Ask for the Lakehouse browser URL and parse workspace ID and Lakehouse ID from it. Do not ask for workspace ID or Lakehouse ID separately during startup; direct IDs are not enough because the browser URL confirms the user is pointing at the intended Fabric item.

## Required path: ask for the Lakehouse URL

Prompt the user with:

> Open Fabric in your browser, navigate to the Lakehouse where you want the Project Osmos run to be stored, copy the full URL from the address bar, and paste it here.

Echo the parsed IDs in full and require explicit user confirmation before doing any API calls.

## Regex

Apply against the pasted URL, case-insensitive:

```text
/groups/(?P<ws>[0-9a-f-]{36})(?:/lakehouses/(?P<lh>[0-9a-f-]{36}))?
```

- `ws` -> workspace ID.
- `lh` -> Lakehouse ID, required for a start flow.
- Both GUIDs are 36 characters with the standard `8-4-4-4-12` hyphen layout.

## Supported URL shapes

| Shape | Example | Yields |
| --- | --- | --- |
| Lakehouse home | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>?experience=power-bi` | workspace + lakehouse |
| Lakehouse explorer with table path | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>/tables/Invoice` | workspace + lakehouse |
| SQL endpoint of the same lakehouse | `https://app.fabric.microsoft.com/groups/<ws>/sqlendpoints/<sql>` | workspace only; ask for the Lakehouse URL |
| Notebook | `https://app.fabric.microsoft.com/groups/<ws>/synapsenotebooks/<nb>` | workspace only; ask for the Lakehouse URL |
| Workspace home | `https://app.fabric.microsoft.com/groups/<ws>/list` | workspace only; ask for the Lakehouse URL |

If the regex matches only the workspace, prompt:

> I read workspace `<ws-short>` from that URL but no Lakehouse. Please open the specific Lakehouse you want Spark to attach to and paste that URL.

If the regex matches nothing, or if the user pasted bare GUIDs instead of a URL, ask the user to repaste the Lakehouse browser URL.

## Supported hosts

Accept public Fabric browser hosts:

| Host | Notes |
| --- | --- |
| `app.fabric.microsoft.com` | Microsoft Fabric portal |
| `app.powerbi.com` | Power BI portal URL that may route to Fabric items |

If the host is not one of the supported public hosts, ask the user to paste a Lakehouse URL from the public Fabric portal.

## Confirmation before any API call

IDs are always UUIDs. Echo the parsed values in this exact shape and require explicit `yes` before proceeding:

```text
Parsed from your URL:
  Workspace ID:  85a394cb-0000-4000-8000-00000000dda8
  Lakehouse ID:  3852746b-0000-4000-8000-00000000b928
  Host:          app.fabric.microsoft.com

Use these? (yes / no / repaste)
```

`repaste` re-runs the prompt. `no` cancels the start flow unless the user provides a new Lakehouse URL.
