#!/usr/bin/env python3
"""Measure AWS EKS + RDS deployment: health, latency, Kubernetes and AWS facts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path


def wait_for_health(url: str, timeout_s: float = 300, poll_interval_s: float = 5) -> tuple[float, bool]:
    """Poll url/healthz until it returns 200 or timeout. Return (elapsed_s, success)."""
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout_s:
            return elapsed, False
        try:
            req = urllib.request.Request(f"{url}/healthz")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return elapsed, True
        except (urllib.error.URLError, urllib.error.HTTPError, Exception):
            pass
        print(f"  waiting for {url}/healthz (elapsed {elapsed:.1f}s)...")
        time.sleep(poll_interval_s)


def get_json(url: str, headers: dict | None = None) -> tuple[int, dict | None]:
    """GET url as JSON. Return (status_code, body_or_none)."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, None


def get_any(url: str, headers: dict | None = None) -> int:
    """GET url and return status code (doesn't parse body)."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return 0


def post_json(url: str, body: dict, headers: dict | None = None) -> tuple[int, dict | None]:
    """POST url with JSON body. Return (status_code, response_body_or_none)."""
    try:
        data = json.dumps(body).encode()
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=data, headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            return e.code, body
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, None


def measure_latency(url: str, endpoint: str, method: str = "GET", body: dict | None = None,
                    n_requests: int = 50, parse_json: bool = True) -> tuple[float, float, int]:
    """Send n_requests to endpoint, record p50 and p95 latencies in ms, and error count."""
    latencies_ms = []
    errors = 0
    for i in range(n_requests):
        start = time.time()
        if method == "GET":
            if parse_json:
                status, _ = get_json(f"{url}{endpoint}")
            else:
                status = get_any(f"{url}{endpoint}")
        else:
            status, _ = post_json(f"{url}{endpoint}", body)
        elapsed_ms = (time.time() - start) * 1000
        if status >= 200 and status < 300:
            latencies_ms.append(elapsed_ms)
        else:
            errors += 1
    if latencies_ms:
        sorted_lat = sorted(latencies_ms)
        p50 = statistics.quantiles(sorted_lat, n=100)[49]
        p95 = statistics.quantiles(sorted_lat, n=100)[94]
        return p50, p95, errors
    return 0.0, 0.0, errors


def check_gzip(url: str, endpoint: str) -> bool:
    """Check if responses to endpoint have gzip content-encoding."""
    try:
        req = urllib.request.Request(f"{url}{endpoint}", headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            enc = resp.headers.get("content-encoding", "").lower()
            return "gzip" in enc
    except Exception:
        return False


def run_cmd(cmd: list[str]) -> dict:
    """Run command, return {stdout: json or text, stderr: error_message or null}."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            try:
                body = json.loads(result.stdout)
                return {"stdout": body, "stderr": None}
            except json.JSONDecodeError:
                return {"stdout": result.stdout, "stderr": None}
        else:
            return {"stdout": None, "stderr": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"stdout": None, "stderr": "timeout"}
    except Exception as e:
        return {"stdout": None, "stderr": str(e)}


def extract_k8s_facts(namespace: str, release: str) -> dict:
    """Extract node counts, instance types, kubelet versions, pod details, LoadBalancer hostname."""
    facts = {}

    # nodes
    result = run_cmd(["kubectl", "get", "nodes", "-o", "json"])
    if result["stderr"]:
        facts["nodes_error"] = result["stderr"]
    else:
        try:
            items = result["stdout"].get("items", [])
            facts["node_count"] = len(items)
            types = []
            versions = []
            for node in items:
                itype = node.get("metadata", {}).get("labels", {}).get("node.kubernetes.io/instance-type", "unknown")
                types.append(itype)
                kv = node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "unknown")
                versions.append(kv)
            facts["instance_types"] = list(set(types))
            facts["kubelet_versions"] = list(set(versions))
        except Exception as e:
            facts["nodes_parse_error"] = str(e)

    # pods
    result = run_cmd(["kubectl", "get", "pods", "-n", namespace, "-o", "json"])
    if result["stderr"]:
        facts["pods_error"] = result["stderr"]
    else:
        try:
            items = result["stdout"].get("items", [])
            pod_facts = []
            for pod in items:
                labels = pod.get("metadata", {}).get("labels", {})
                if labels.get("app.kubernetes.io/instance") == release or labels.get("app") == release:
                    spec = pod.get("spec", {}).get("containers", [{}])[0]
                    image = spec.get("image", "unknown")
                    status = pod.get("status", {})
                    phase = status.get("phase", "unknown")
                    ready = sum(1 for c in status.get("containerStatuses", []) if c.get("ready"))
                    restart_count = status.get("containerStatuses", [{}])[0].get("restartCount", 0)
                    pod_facts.append({
                        "phase": phase,
                        "ready": ready,
                        "restart_count": restart_count,
                        "image": image
                    })
            facts["pods"] = pod_facts
        except Exception as e:
            facts["pods_parse_error"] = str(e)

    # LoadBalancer hostname
    result = run_cmd(["kubectl", "get", "svc", "-n", namespace, "-o", "json"])
    if result["stderr"]:
        facts["svc_error"] = result["stderr"]
    else:
        try:
            items = result["stdout"].get("items", [])
            for svc in items:
                labels = svc.get("metadata", {}).get("labels", {})
                if labels.get("app.kubernetes.io/instance") == release or labels.get("app") == release:
                    lbs = svc.get("status", {}).get("loadBalancer", {}).get("ingress", [])
                    if lbs:
                        facts["loadbalancer_hostname"] = lbs[0].get("hostname") or lbs[0].get("ip")
                    break
        except Exception as e:
            facts["svc_parse_error"] = str(e)

    return facts


def extract_eks_facts(cluster: str, region: str) -> dict:
    """Extract EKS cluster version and platformVersion."""
    result = run_cmd(["aws", "eks", "describe-cluster", "--name", cluster, "--region", region])
    facts = {}
    if result["stderr"]:
        facts["error"] = result["stderr"]
        return facts
    try:
        cluster_info = result["stdout"].get("cluster", {})
        facts["version"] = cluster_info.get("version")
        facts["platformVersion"] = cluster_info.get("platformVersion")
    except Exception as e:
        facts["parse_error"] = str(e)
    return facts


def extract_rds_facts(cluster_name: str, region: str) -> dict:
    """Extract RDS instances matching cluster name: engine, version, instance class, storage, multi_az."""
    result = run_cmd(["aws", "rds", "describe-db-instances", "--region", region])
    instances = []
    if result["stderr"]:
        return {"error": result["stderr"]}
    try:
        for db in result["stdout"].get("DBInstances", []):
            if db.get("DBInstanceIdentifier", "").startswith(cluster_name):
                instances.append({
                    "engine": db.get("Engine"),
                    "engine_version": db.get("EngineVersion"),
                    "instance_class": db.get("DBInstanceClass"),
                    "allocated_storage_gb": db.get("AllocatedStorage"),
                    "multi_az": db.get("MultiAZ")
                })
    except Exception as e:
        return {"parse_error": str(e)}
    return {"instances": instances}


def count_nat_gateways(region: str) -> dict:
    """Count NAT gateways in region."""
    result = run_cmd(["aws", "ec2", "describe-nat-gateways", "--region", region])
    if result["stderr"]:
        return {"error": result["stderr"]}
    try:
        nats = result["stdout"].get("NatGateways", [])
        return {"count": len(nats)}
    except Exception as e:
        return {"parse_error": str(e)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure AWS EKS + RDS deployment.")
    parser.add_argument("--url", required=True, help="Base URL of the deployed app")
    parser.add_argument("--out", required=True, help="Output JSON file path")
    parser.add_argument("--requests", type=int, default=50, help="Number of latency requests per endpoint")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace")
    parser.add_argument("--release", required=True, help="Helm release name")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument("--cluster", required=True, help="EKS cluster name")
    args = parser.parse_args()

    print(f"Measuring {args.url}...")
    measured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    results = {
        "measured_at": measured_at,
        "region": args.region,
        "cluster": args.cluster,
        "url": args.url,
    }

    # Step 1: Wait for health
    print("Step 1: Waiting for /healthz...")
    elapsed, success = wait_for_health(args.url)
    results["time_to_healthy_s"] = round(elapsed, 2)
    if not success:
        print("  FAILED: endpoint did not become healthy")
        return
    print(f"  OK: healthy in {elapsed:.1f}s")

    # Step 2: GET /readyz and /api/health
    print("Step 2: GET /readyz and /api/health...")
    status_readyz, _ = get_json(f"{args.url}/readyz")
    status_health, body_health = get_json(f"{args.url}/api/health")
    results["health"] = {
        "readyz_status": status_readyz,
        "api_health_status": status_health,
        "api_health_body": body_health or {}
    }
    print(f"  /readyz: {status_readyz}, /api/health: {status_health}")

    # Step 3: POST /api/demo/load
    print("Step 3: Loading demo data...")
    status, body = post_json(f"{args.url}/api/demo/load", {"reset": True})
    receipts_loaded = body.get("receipts_loaded", 0) if body else 0
    results["demo_receipts_loaded"] = receipts_loaded
    print(f"  Loaded {receipts_loaded} receipts")

    # Step 4a: Test latency for GET endpoints
    print("Step 4a: Testing latency (GET endpoints)...")
    latency = {}
    for endpoint in ["/api/health", "/api/prices?method=weighted", "/api/insights?trip_cost=5", "/"]:
        print(f"  {endpoint}...")
        parse_json = endpoint != "/"
        p50, p95, errors = measure_latency(args.url, endpoint, n_requests=args.requests, parse_json=parse_json)
        latency[endpoint] = {"p50_ms": round(p50, 2), "p95_ms": round(p95, 2),
                             "errors": errors, "n": args.requests}
    results["latency"] = latency

    # Step 4b: GET shopping list and stores for the plan endpoint
    print("Step 4b: Fetching shopping list and stores...")
    _, shopping_list = get_json(f"{args.url}/api/demo/shopping-list")
    _, stores_resp = get_json(f"{args.url}/api/stores")
    stores = stores_resp if isinstance(stores_resp, list) else []

    # Step 4c: Test latency for POST /api/plan
    print("Step 4c: Testing latency (POST /api/plan)...")
    if shopping_list and stores:
        plan_body = {
            "items": shopping_list,
            "stores": stores,
            "trip_cost": 5,
            "max_stores": None,
            "price_method": "weighted"
        }
        plan_latencies_ms = []
        plan_error = 0
        for _ in range(args.requests):
            start = time.time()
            status, resp = post_json(f"{args.url}/api/plan", plan_body)
            elapsed_ms = (time.time() - start) * 1000
            if status >= 200 and status < 300:
                plan_latencies_ms.append(elapsed_ms)
            else:
                plan_error += 1

        plan_results = {}
        if plan_latencies_ms:
            sorted_lat = sorted(plan_latencies_ms)
            plan_results["latency_ms"] = round(statistics.mean(sorted_lat), 2)
            status, resp = post_json(f"{args.url}/api/plan", plan_body)
            if resp and "optimal" in resp:
                optimal = resp.get("optimal", {})
                savings = resp.get("savings_vs_single_store", {})
                plan_results["savings_vs_single_store"] = savings
        results["plan"] = plan_results

    # Step 4d: Check gzip encoding on /api/prices
    print("Step 4d: Checking gzip encoding...")
    has_gzip = check_gzip(args.url, "/api/prices?method=weighted")
    results["gzip"] = has_gzip

    # Step 5: Kubernetes and AWS facts
    print("Step 5: Collecting Kubernetes and AWS facts...")
    k8s_facts = extract_k8s_facts(args.namespace, args.release)
    eks_facts = extract_eks_facts(args.cluster, args.region)
    rds_facts = extract_rds_facts(args.cluster, args.region)
    nat_facts = count_nat_gateways(args.region)

    results["kubernetes"] = k8s_facts
    results["eks"] = eks_facts
    results["rds"] = rds_facts
    results["nat_gateways"] = nat_facts.get("count", nat_facts.get("error"))

    results["notes"] = "Single run from a laptop over the public internet; latencies include the network path to us-east-2."

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nResults written to {out_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"URL:                    {args.url}")
    print(f"Time to healthy:        {results['time_to_healthy_s']:.1f}s")
    print(f"Demo receipts loaded:   {results['demo_receipts_loaded']}")
    print(f"GZip enabled:           {results['gzip']}")
    print(f"\nLatency (p50/p95 ms):")
    for endpoint, stats in results["latency"].items():
        print(f"  {endpoint:40} {stats['p50_ms']:7.1f} / {stats['p95_ms']:7.1f}")
    if "plan" in results and results["plan"]:
        print(f"\nPlan optimization:")
        print(f"  Latency (mean):         {results['plan'].get('latency_ms', 0):.1f} ms")
    if "kubernetes" in results and results["kubernetes"]:
        k8s = results["kubernetes"]
        print(f"\nKubernetes:")
        print(f"  Nodes:                  {k8s.get('node_count', 'unknown')}")
        print(f"  Instance types:         {', '.join(k8s.get('instance_types', []))}")
    if "eks" in results and results["eks"]:
        eks = results["eks"]
        print(f"\nEKS:")
        print(f"  Cluster version:        {eks.get('version', 'unknown')}")
        print(f"  Platform version:       {eks.get('platformVersion', 'unknown')}")
    if "rds" in results and results["rds"]:
        rds = results["rds"]
        insts = rds.get("instances", [])
        if insts:
            inst = insts[0]
            print(f"\nRDS:")
            print(f"  Engine:                 {inst.get('engine')} {inst.get('engine_version')}")
            print(f"  Instance class:         {inst.get('instance_class')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
