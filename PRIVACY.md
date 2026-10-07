# Privacy and telemetry

Version 1.0.0 removes this package's standalone task execution skill.
Microsoft Skills for Fabric (SFF) supplies task execution. That
replacement skill, the coding client, and Microsoft Fabric services have their
own data collection and telemetry behavior; consult their privacy notices.
The public `project-osmos-migration` skill provides installation and verification
guidance only. It contains no authentication or task execution helper.


You can uninstall or disable this plugin in your coding client.
That does not disable SFF, stop a legacy local recovery process, cancel a remote
task, or turn off the coding client's or service's telemetry. Preserve legacy
`.dataprojects` task state and follow the
[migration precautions](README.md#existing-tasks-and-legacy-recovery)
before updating or uninstalling an active legacy installation.

## Data Collection

The software may collect information about you and your use of the software and send it to Microsoft. Microsoft may use this information to provide services and improve our products and services. Telemetry controls, where available, are provided by the relevant coding client, SFF implementation, or service; this package has no telemetry setting. There are also some features in the software that may enable you and Microsoft to collect data from users of your applications. If you use these features, you must comply with applicable law, including providing appropriate notices to users of your applications together with a copy of Microsoft's privacy statement. Our privacy statement is located at [https://go.microsoft.com/fwlink/?LinkID=824704](https://go.microsoft.com/fwlink/?LinkID=824704). You can learn more about data collection and use in the help documentation and our privacy statement. Your use of the software operates as your consent to these practices.
