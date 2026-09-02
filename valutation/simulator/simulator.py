import json


class TaskStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class Node:
    def __init__(self, name, properties, location, memory=None):
        self.name = name
        self.properties = properties  # alpha(n)
        self.location = location  # loc(n)
        self.memory = set(memory) if memory else set()  # Lambda(n)


class Dataset:
    def __init__(
        self, name, req_props, req_geo, contexts, size, is_static, local_nodes
    ):
        self.name = name
        self.req_props = req_props  # beta(d)
        self.req_geo = req_geo  # geo(d)
        self.contexts = set(contexts)  # ctx(d)
        self.size = size  # size(d)
        self.is_static = is_static
        self.local_nodes = set(local_nodes)  # lambda(d)


class Task:
    def __init__(self, name, issuer, req_datasets, req_props, req_geo):
        self.name = name
        self.issuer = issuer  # iss(t)
        self.req_datasets = req_datasets  # req(t)
        self.req_props = req_props  # beta(t)
        self.req_geo = req_geo  # geo(t)

        # State tracking
        self.status = TaskStatus.PENDING
        self.assigned_nodes = []  # List of all nodes that can execute the task 
        self.score = None
        self.rejection_phase = None
        self.rejection_reason = None


class Issuer:
    def __init__(self, name, auth_contexts):
        self.name = name
        self.auth_contexts = set(auth_contexts)  # auth(i)


class ClusterSimulator:
    """
    Exclusively handles the execution of the scheduling pipeline and state transitions.
    """

    def __init__(self, config_json):
        config = json.loads(config_json)
        self.geo_groups = {k: set(v) for k, v in config["geo_groups"].items()}
        self.max_levels = config["max_levels"]

        self.nodes = {
            n["name"]: Node(
                n["name"], n["properties"], n["location"], n.get("memory", [])
            )
            for n in config["nodes"]
        }
        self.datasets = {
            d["name"]: Dataset(
                d["name"],
                d["req_props"],
                d["req_geo"],
                d["contexts"],
                d["size"],
                d["is_static"],
                d["local_nodes"],
            )
            for d in config["datasets"]
        }
        self.issuers = {
            i["name"]: Issuer(i["name"], i["auth_contexts"]) for i in config["issuers"]
        }

        self.conflicts = set()
        for c1, c2 in config["conflicts"]:
            self.conflicts.add((c1, c2))
            self.conflicts.add((c2, c1))

        self.task_history = []

    def resolve_geo(self, geo_req):
        return self.geo_groups.get(geo_req, {geo_req})

    def _reject_task(self, task, phase, reason):
        task.status = TaskStatus.REJECTED
        task.rejection_phase = phase
        task.rejection_reason = reason
        self.task_history.append(task)
        return task

    def assign_task(self, task):
        issuer = self.issuers[task.issuer]
        req_ds = [self.datasets[d] for d in task.req_datasets]

        # 1. Validation Phase
        for ds in req_ds:
            if not ds.contexts.issubset(issuer.auth_contexts):
                return self._reject_task(
                    task,
                    "Validation",
                    f"c_auth violation on {ds.name}. Issuer lacks contexts: {ds.contexts - issuer.auth_contexts}",
                )

        # 2. Translation Phase
        beta_star = {p: task.req_props.get(p, 0) for p in self.max_levels}
        for ds in req_ds:
            for p, val in ds.req_props.items():
                beta_star[p] = max(beta_star[p], val)

        geo_star = self.resolve_geo(task.req_geo)
        for ds in req_ds:
            geo_star = geo_star.intersection(self.resolve_geo(ds.req_geo))

        if not geo_star:
            return self._reject_task(
                task, "Translation", "geo*(t) is empty due to geographical conflict"
            )

        ctx_star = set().union(*(ds.contexts for ds in req_ds))

        # 3. Scheduler Phase (Filter)
        admissible_nodes = []
        for _, node in self.nodes.items():
            if any(node.properties.get(p, 0) < beta_star[p] for p in self.max_levels):
                continue
            if node.location not in geo_star:
                continue

            static_violation = False
            for ds in req_ds:
                if ds.is_static and node.name not in ds.local_nodes:
                    static_violation = True
                    break
            if static_violation:
                continue

            wall_violation = False
            for auth_ctx in issuer.auth_contexts:
                for mem_ctx in node.memory:
                    if (auth_ctx, mem_ctx) in self.conflicts:
                        wall_violation = True
                        break
                if wall_violation:
                    break
            if wall_violation:
                continue

            admissible_nodes.append(node)

        if not admissible_nodes:
            return self._reject_task(
                task, "Scheduler (Filter)", "No nodes satisfy all C_T U C_D constraints"
            )

        # 4. Scheduler Phase (Scoring)
        best_nodes = []
        best_score = -1.0
        w_prop, w_transfer = 1.0, 1.0

        for node in admissible_nodes:
            delta, delta_max = 0, 0
            for p, max_val in self.max_levels.items():
                if beta_star[p] < max_val:
                    delta += (node.properties.get(p, 0) - beta_star[p]) / (
                        max_val - beta_star[p]
                    )
                    delta_max += 1
            phi_prop = 1 - (delta / delta_max) if delta_max > 0 else 1.0

            total_size = sum(ds.size for ds in req_ds)
            remote_size = sum(
                ds.size for ds in req_ds if node.name not in ds.local_nodes
            )
            phi_transfer = 1 - (remote_size / total_size) if total_size > 0 else 1.0

            score = (w_prop * phi_prop) + (w_transfer * phi_transfer)

            # Handle optimal ties correctly
            if score > best_score + 1e-9:  # Add tolerance for float comparison
                best_score = score
                best_nodes = [node]
            elif abs(score - best_score) <= 1e-9:
                best_nodes.append(node)

        # 5. PostBind Phase
        task.status = TaskStatus.COMPLETED
        task.assigned_nodes = [n.name for n in best_nodes]
        task.score = best_score

        # Update memory of the first node to simulate a deterministic progression
        if best_nodes:
            best_nodes[0].memory.update(ctx_star)

        self.task_history.append(task)
        return task
