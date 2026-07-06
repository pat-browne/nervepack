---
kind: topic
name: k8s-serverless-compute
title: Serverless-Style Batch Compute on Kubernetes
description: >
  Architecturally viable patterns for ephemeral, autoscaling batch compute on AKS with
  Airflow orchestration — comparable to Databricks Serverless and EMR Serverless. Covers
  DuckDB/KPO, Spark Operator, KubeRay/RayJob, and KEDA ScaledJobs with honest trade-off
  comparisons. Backed by adversarially-verified deep research (2026-07-06).
tags: [kubernetes, aks, airflow, spark, duckdb, ray, keda, data-platform, architecture]
research_artifact: https://claude.ai/code/artifact/772e5e98-40e3-4908-a1bd-82eb44918f45
last_updated: 2026-07-06
---

# Serverless-Style Batch Compute on Kubernetes (AKS + Airflow)

> **Research basis**: 105-agent deep-research workflow, 23 sources fetched, 25 claims
> adversarially verified (3-vote), 15 confirmed, 10 refuted. Primary sources only for
> confirmed claims. Sources dated through July 2026.

## The Problem

The team wants ephemeral, autoscaling batch compute on AKS with Airflow orchestration —
comparable to what Databricks Serverless and EMR Serverless provide as managed services.
The key property: scale to zero when idle (no cost for unused capacity).

---

## The Managed Baseline: Azure Databricks Serverless

Before evaluating self-managed alternatives, the hard constraints of Databricks Serverless
define what you'd be taking on operationally if you accepted them, and what you'd gain by
not.

| Constraint | Detail |
|---|---|
| **7-day hard runtime cap** | Runs exceeding 7 days are terminated without retry. Break long workloads into smaller runs or use classic compute. |
| **Spark Connect API only** | RDD-dependent workloads require code changes before migration. DataFrames/SQL are fine. |
| **4–6 min cold start (standard mode)** | Performance-optimized mode starts faster at higher DBU cost. |
| **No infrastructure control** | Autoscaling and Photon are force-enabled. No instance type selection, no autoscaling overrides. |

Sources: `learn.microsoft.com/en-us/azure/databricks/compute/serverless/limitations`,
`learn.microsoft.com/en-us/azure/databricks/jobs/run-serverless-jobs`

---

## The Universal Caveat (research-confirmed)

**None of the self-managed patterns below achieve node-level scale-to-zero on their own.**

KEDA, KubeRay, and Spark Operator all achieve pod/job-level scale-to-zero. For nodes to
actually deprovision (eliminating VM cost at idle), you must separately configure:
- **AKS Cluster Autoscaler** with `min=0` on the relevant node pool(s), OR
- **Karpenter** on AKS with a zero-node floor

This is the key operational gap vs. managed serverless. Every pattern below requires this
infrastructure layer. The research killed the claims that KEDA, KubeRay, and Trino
"provide true scale-to-zero" with 0-3 adversarial votes each.

---

## Four Viable Patterns

### 1. DuckDB via KubernetesPodOperator

**Confidence: High (3-0 verified) · Complexity: Lowest**

The `airflow-duckdb` library wraps `KubernetesPodOperator` to spawn an ephemeral pod per
Airflow task rather than running DuckDB in-process on the Airflow worker. Each task call
specifies independent CPU/memory requests; pods exist only during query execution.

**How the Airflow integration works:**
- Drop `DuckDBPodOperator` into any DAG as a replacement for in-process DuckDB tasks
- No cluster-side controller required — pure KPO
- Decouples DuckDB compute budget from Airflow worker sizing

**Scale-to-zero:** Pod-level zero is native (pod terminates after task). Node-level zero
via AKS CA with zero-node pool minimum. Cold start ≈ 10–30s (pod scheduling time).

**Fit:** GB-scale SQL batch jobs, single-node ELT, teams new to K8s compute patterns.

**Anti-fit:** TB-scale workloads, distributed shuffle, multi-node parallelism. DuckDB is
single-node by architecture — not a Spark replacement for large distributed jobs.

**Risks:**
- Community library (`hussein-awala/airflow-duckdb`), not officially supported
- One pod per Airflow task (may contain multiple SQL statements), not one pod per query
- No distributed compute; must pair with Spark/Ray for large workloads

Source: `github.com/hussein-awala/airflow-duckdb`

---

### 2. Spark Operator (Kubeflow)

**Confidence: High (3-0 verified) · Maturity: Beta (v1beta2)**

The Spark Operator installs a Kubernetes controller that manages a `SparkApplication` CRD.
Airflow's `SparkKubernetesOperator` creates a `SparkApplication` resource; the controller
handles driver + executor pod lifecycle. After job completion: executor pods fully
terminate; driver pod persists in `Completed` state consuming **zero CPU/memory** until
garbage collected.

**Dynamic Resource Allocation:**
- Enabled via shuffle tracking: `spark.dynamicAllocation.shuffleTracking.enabled=true`
- Described by the operator as a **"limited form"** of DRA (External Shuffle Service for
  Kubernetes is unimplemented — listed on the upstream roadmap, JIRA SPARK-25796)
- Configured with `initialExecutors`, `minExecutors`, `maxExecutors` in the CRD
- Apache Celeborn exists as a third-party remote shuffle service but adds operational
  overhead and is not native Spark

**Airflow integration:**
- `SparkKubernetesOperator` from `apache-airflow-providers-cncf-kubernetes`
- Requires Spark Operator CRD + controller pre-installed on cluster
- References YAML manifests, not spark-submit arguments

**Fit:** Spark-native workloads, existing PySpark/Scala codebases, heavy shuffle workloads.

**Risks:**
- **Beta status (API `v1beta2`, v2.5.1, June 2025)** — CRD API not guaranteed stable
  across minor version upgrades. Meaningful production risk for long-lived pipelines.
- No external shuffle service (DRA is functional but limited)
- Node-level scale-to-zero requires AKS CA with zero-node min pool

Sources: `spark.apache.org/docs/latest/running-on-kubernetes.html`,
`kubeflow.github.io/spark-operator/docs/user-guide.html`,
`airflow.apache.org/docs/apache-airflow-providers-cncf-kubernetes/...`

---

### 3. KubeRay / RayJob

**Confidence: High (3-0 verified) · Most Complete Serverless Analogue**

`RayJob` is a CRD that automatically creates a `RayCluster`, runs the job, then tears the
entire cluster down on completion when `shutdownAfterJobFinishes: true` (default: false).
This is the closest available analogue to EMR Serverless or Databricks Serverless ephemeral
cluster semantics available on Kubernetes.

**Autoscaling design (key differentiator):**
KubeRay's autoscaler scales on **logical resource requests** declared in `@ray.remote`
decorators — not CPU/memory utilization metrics. Scale-out triggers on pending task queues,
not node saturation. This prevents both under- and over-provisioning during steady-state
execution. (Autoscaler v2, Ray 2.10+, refines this loop.)

**Airflow integration:** No first-party Airflow provider as of 2025. Community-documented
patterns: submit `RayJob` via `KubernetesPodOperator` or the Ray Jobs HTTP API from a
`PythonOperator`.

**Fit:** ML inference, Python-first distributed workloads, batch inference, teams wanting
the most managed-like serverless experience on K8s.

**Anti-fit:** Pure SQL/Spark workloads; teams with no Python distributed programming
experience; teams requiring a first-party Airflow provider.

**Risks:**
- KubeRay alone does not guarantee zero idle node costs (confirmed 0-3 refuted)
- No first-party Airflow provider — integration is bespoke
- Requires workloads to be written against the Ray API (`@ray.remote`)

Sources: `docs.ray.io/en/latest/cluster/kubernetes/examples/rayjob-batch-inference-example.html`,
`docs.ray.io/en/latest/cluster/kubernetes/user-guides/configuring-autoscaling.html`

---

### 4. KEDA ScaledJobs (cross-cutting layer)

**Confidence: Medium (2-1 verified) · AKS-native**

KEDA's `ScaledJob` resource creates individual Kubernetes Jobs that run to completion and
terminate. When no work items are queued, zero jobs are created. This is the batch-specific
variant of KEDA — `ScaledObject` scales long-running Deployments; `ScaledJob` scales
ephemeral batch Jobs.

KEDA is **first-class on AKS** (natively integrated, not an add-on).

**Role in architecture:** KEDA is best thought of as a **cross-cutting scaling layer**, not
a compute engine. It can front-load DuckDB pods, Spark driver pods, or custom worker images
behind a queue, providing a unified event-driven trigger model across all patterns above.

**Airflow integration:** The common KEDA+Airflow pattern scales CeleryExecutor worker
Deployments via `ScaledObject`. Using `ScaledJob` for batch compute requires Airflow to
publish work items to an event source (Azure Service Bus, Redis, Kafka) that KEDA monitors.
This is architecturally sound but requires bespoke queue wiring (not a direct trigger).

**Fit:** Teams already using message queues for task distribution; queue-based worker
patterns; adding event-driven scaling to any container image.

**Risks:**
- KEDA operates at pod/job level only — node-level zero requires AKS CA or Karpenter
- Airflow + ScaledJob integration is community-confirmed (apache/airflow #35107) but not
  in official Airflow docs — bespoke queue wiring required
- KEDA provides no data processing runtime; must be paired with a compute image

Sources: `learn.microsoft.com/en-us/azure/aks/keda-about`,
`keda.sh/docs/2.20/concepts/scaling-jobs/`

---

## Comparison Matrix

| Pattern | Maturity | Distributed | Pod-zero | Node-zero | Airflow | Cold start | Best for |
|---|---|---|---|---|---|---|---|
| DuckDB / KPO | Community | Single-node only | Native | via AKS CA | KPO drop-in | 10–30s | GB-scale SQL |
| Spark Operator | Beta v1beta2 | Full Spark | Exec pods terminate | via AKS CA | SparkKubernetesOperator | 1–3min + DRA | Spark-native workloads |
| KubeRay / RayJob | GA (Ray 2.x) | Distributed | shutdownAfterJob | via AKS CA | Bespoke | 30s–2min | ML / Python dist. |
| KEDA ScaledJobs | Stable | Depends on image | Jobs terminate | via AKS CA | Queue wiring reqd. | Pod schedule time | Queue-driven workers |
| Databricks Serverless | Managed | Full Spark | Managed | Managed | First-party | 4–6 min | Managed simplicity |

---

## Trino — Not Validated

Trino was a research target but produced **no confirmed findings**. The claim that Trino
supports scale-to-zero via KEDA (`server.keda.minReplicaCount: 0`) was refuted 0-3.
Primary evidence came from a secondary AI-generated source (deepwiki.com) and a GitHub
issue; production case studies with Trino+KEDA set `minReplicaCount: 1`, not 0.

The official Trino Helm chart exposes KEDA integration, but scale-to-zero viability in
production is unconfirmed. **Treat Trino as an always-on query engine, not an ephemeral
batch substrate.**

---

## Refuted Claims (do not propagate)

These claims appear in blog posts and vendor marketing but did not survive adversarial
verification:

| Claim | Vote | Why it failed |
|---|---|---|
| KEDA provides "true scale-to-zero" | 0-3 | Pod-level only; node-level needs separate infra |
| RayJob achieves node-level scale-to-zero with `--min-nodes 0` | 0-3 | KubeRay alone doesn't guarantee this |
| Trino + KEDA achieves scale-to-zero | 0-3 | No primary source; production deployments use min=1 |
| Managed serverless maintains a warm pool making it cost-equivalent to classic clusters | 0-3 | Blog-quality source, contradicted by primary docs |
| Serverless only wins for jobs under 5 minutes | 0-3 | Unsubstantiated; depends entirely on workload mix |

---

## Open Questions (require empirical testing)

1. **Cold-start comparison**: What is the actual end-to-end latency (Airflow trigger → first
   task execution) for each pattern on AKS with node autoscaling enabled vs. Databricks
   Serverless standard mode's 4–6 min?

2. **Celeborn viability**: Is Apache Celeborn mature enough on AKS to replace shuffle
   tracking for Spark DRA in production, and what is the overhead of running a persistent
   Celeborn cluster?

3. **TCO comparison**: What is the realistic total cost of ownership for self-managed Spark
   Operator or KubeRay on AKS reserved instances vs. Databricks Serverless DBU pricing
   for the team's actual workload mix, accounting for platform engineering time?

4. **Trino at zero**: Has Trino on Kubernetes achieved viable scale-to-zero in any
   production deployment, or is it only appropriate as a persistent always-on engine?

---

## Decision Path

```
Single-node SQL, <100GB, fast iteration?
  → DuckDB / KubernetesPodOperator (lowest overhead, easiest Airflow drop-in)

Existing PySpark/Scala workloads, distributed shuffle required?
  → Spark Operator (accept beta-grade CRD API, plan for upgrades)

Python-first workloads, ML inference, want the closest K8s analogue to managed serverless?
  → KubeRay / RayJob (most complete analogue; invest in bespoke Airflow wiring)

Already using a message queue, want event-driven scaling across any container?
  → KEDA ScaledJobs (cross-cutting layer, pairs with any of the above)
```

All paths require: AKS Cluster Autoscaler or Karpenter with zero-node minimum on batch
node pools to achieve true idle-cost-zero at the node level.
