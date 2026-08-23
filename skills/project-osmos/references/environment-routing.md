# Environment routing

Read this reference before workspace/Lakehouse name discovery, metadata lookup, token acquisition, or any other Fabric API call.

Project Osmos public runs target production Fabric. Workspace and Lakehouse IDs may come from Fabric page context, Microsoft Fabric Skills discovery, or a validated Lakehouse browser URL.

## Routing table

| Context | Family | Use when | Required extras |
| --- | --- | --- | --- |
| `prod` | Production-shape | Public Fabric tenant usage | Azure CLI access to the tenant, workspace/lakehouse permissions |


## Rules

- Do not ask for context, workspace ID, or lakehouse ID as separate startup questions.
- For public production runs, resolve supplied workspace and Lakehouse names with Microsoft Fabric Skills; a browser URL is optional.
