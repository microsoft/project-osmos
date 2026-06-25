# Environment routing

Project Osmos tasks can run against multiple Fabric environments. Derive the target environment from the pasted Lakehouse browser URL before deriving hosts or acquiring tokens.

## Routing table

| Environment | Family | Use when | Required extras |
| --- | --- | --- | --- |
| `prod` | Production-shape | Public Fabric tenant usage | Azure CLI access to the tenant, workspace/lakehouse permissions |
| `msit` | Production-shape | MSIT environment validation | Environment-specific public API, WABI, and workload hosts |


## Rules

- There is no default environment; the environment must be parsed from the Lakehouse URL host.
- Do not ask for environment, workspace ID, or lakehouse ID as separate startup questions.
- If the Lakehouse URL does not parse to an environment, workspace ID, and lakehouse ID, ask the user to repaste the specific Lakehouse URL from the target Fabric portal for that environment.


- For deployed environments, do not add the local `fabric_environment` query parameter unless the service explicitly requires it.
- If the user provides names or IDs instead of a URL, ask for the Lakehouse browser URL so the environment can be derived from the host.
