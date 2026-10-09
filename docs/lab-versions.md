# Lab Versions

Pinned baseline for the local SRE Platform Demo lab used by Praeva experiments.

| Component | Version |
| --- | --- |
| Kind node image | `kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f` |
| kube-prometheus-stack chart | `88.6.2` |
| Loki chart | `7.3.0` |
| Promtail chart | `6.17.1` |
| ArgoCD chart | `10.6.4` |

These versions match the last known deployed lab baseline captured before rebuilding the Kind cluster for Praeva Spike 001. Version pins may be overridden explicitly through the corresponding environment variables in the local scripts when testing upgrades on purpose.
