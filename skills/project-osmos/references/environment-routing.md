# Environment routing

The public Project Osmos skill supports public Microsoft Fabric URLs. The skill should not expose or ask users to choose deployment rings or service environments.

## Rules

- Derive workspace and Lakehouse IDs from the user's Lakehouse browser URL.
- Accept public Fabric browser hosts documented in [URL parsing](url-parsing.md).
- Do not ask for environment names, workspace IDs, or Lakehouse IDs as separate startup questions.
- If the Lakehouse URL does not parse to a workspace ID and Lakehouse ID, ask the user to repaste the specific Lakehouse URL from Fabric.
- Route construction and authorization are handled by [Authentication and route construction](auth-and-routing.md).
